\set ON_ERROR_STOP on
\connect ptm_prod

SET search_path TO ptm, public;

-- 1) Convert protein_sequence to use surrogate primary key (avoid long-text PK index overflow)
ALTER TABLE ptm.protein_sequence
  ADD COLUMN IF NOT EXISTS id BIGINT GENERATED ALWAYS AS IDENTITY;

UPDATE ptm.protein_sequence
SET id = DEFAULT
WHERE id IS NULL;

DO $$
DECLARE
  v_pk_name TEXT;
BEGIN
  SELECT conname
  INTO v_pk_name
  FROM pg_constraint
  WHERE conrelid = 'ptm.protein_sequence'::regclass
    AND contype = 'p'
  LIMIT 1;

  IF v_pk_name IS NOT NULL THEN
    EXECUTE format('ALTER TABLE ptm.protein_sequence DROP CONSTRAINT %I', v_pk_name);
  END IF;
END $$;

ALTER TABLE ptm.protein_sequence
  ALTER COLUMN protein SET NOT NULL;

ALTER TABLE ptm.protein_sequence
  ALTER COLUMN gene_name SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conrelid = 'ptm.protein_sequence'::regclass
      AND conname = 'protein_sequence_id_pkey'
  ) THEN
    ALTER TABLE ptm.protein_sequence
      ADD CONSTRAINT protein_sequence_id_pkey PRIMARY KEY (id);
  END IF;
END $$;

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

-- 2) Refresh protein import function: upsert by gene_name (not by long protein text)
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
