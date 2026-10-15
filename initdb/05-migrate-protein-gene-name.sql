\set ON_ERROR_STOP on
\connect ptm_prod

SET search_path TO ptm, public;

ALTER TABLE ptm.protein_sequence
  ADD COLUMN IF NOT EXISTS gene_name TEXT;

UPDATE ptm.protein_sequence
SET gene_name = CONCAT('UNKNOWN_', SUBSTR(MD5(protein), 1, 12))
WHERE gene_name IS NULL OR BTRIM(gene_name) = '';

ALTER TABLE ptm.protein_sequence
  ALTER COLUMN gene_name SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'ptm.protein_sequence'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) ILIKE '%(gene_name)%'
  ) THEN
    ALTER TABLE ptm.protein_sequence
      ADD CONSTRAINT uq_protein_sequence_gene_name UNIQUE (gene_name);
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_protein_sequence_gene_name
  ON ptm.protein_sequence(gene_name);

CREATE INDEX IF NOT EXISTS idx_gs_ptm_gene_name
  ON ptm.gs_ptm(gene_name);

ALTER TABLE ptm.stg_protein_sequence
  ADD COLUMN IF NOT EXISTS gene_name TEXT;

CREATE OR REPLACE FUNCTION ptm.apply_stg_protein_sequence(
  p_source_name TEXT DEFAULT 'manual_protein_sequence_import',
  p_source_version TEXT DEFAULT NULL,
  p_notes TEXT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
  v_batch_id BIGINT;
BEGIN
  INSERT INTO ptm.import_batch (source_type, source_name, source_version, notes)
  VALUES ('protein_sequence', p_source_name, p_source_version, p_notes)
  RETURNING batch_id INTO v_batch_id;

  WITH src_raw AS (
    SELECT DISTINCT
      UPPER(REGEXP_REPLACE(BTRIM(s.protein), '\s+', '', 'g')) AS protein,
      BTRIM(s.gene_name) AS gene_name
    FROM ptm.stg_protein_sequence s
    WHERE NULLIF(BTRIM(s.protein), '') IS NOT NULL
      AND NULLIF(BTRIM(s.gene_name), '') IS NOT NULL
  ),
  src AS (
    SELECT DISTINCT ON (gene_name)
      protein,
      gene_name
    FROM src_raw
    ORDER BY gene_name, protein DESC
  )
  INSERT INTO ptm.protein_sequence (
    protein,
    gene_name,
    source_batch_id
  )
  SELECT
    src.protein,
    src.gene_name,
    v_batch_id
  FROM src
  ON CONFLICT (gene_name) DO UPDATE
  SET protein = EXCLUDED.protein,
      source_batch_id = EXCLUDED.source_batch_id;

  RETURN v_batch_id;
END;
$$;
