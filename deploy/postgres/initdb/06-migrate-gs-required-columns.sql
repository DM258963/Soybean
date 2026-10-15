\set ON_ERROR_STOP on
\connect ptm_prod

SET search_path TO ptm, public;

CREATE OR REPLACE FUNCTION ptm.apply_stg_gs_ptm(
  p_source_name TEXT DEFAULT 'manual_gs_import',
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
  VALUES ('gs', p_source_name, p_source_version, p_notes)
  RETURNING batch_id INTO v_batch_id;

  INSERT INTO ptm.ptm_type_dict (ptm_types)
  SELECT DISTINCT BTRIM(s.ptm_types)
  FROM ptm.stg_gs_ptm s
  WHERE NULLIF(BTRIM(s.ptm_types), '') IS NOT NULL
    AND UPPER(BTRIM(s.ptm_types)) <> 'DA'
    AND NULLIF(BTRIM(s.gene_name), '') IS NOT NULL
    AND s.position IS NOT NULL
    AND s.position > 0
    AND NULLIF(BTRIM(s.amino_acid), '') IS NOT NULL
  ON CONFLICT (ptm_types) DO NOTHING;

  INSERT INTO ptm.gs_ptm (
    organism,
    ptm_types,
    protein_accession,
    position,
    amino_acid,
    protein_description,
    gene_name,
    source_batch_id
  )
  SELECT
    COALESCE(NULLIF(BTRIM(s.organism), ''), 'Unknown'),
    BTRIM(s.ptm_types),
    COALESCE(NULLIF(BTRIM(s.protein_accession), ''), 'Unknown'),
    s.position,
    BTRIM(s.amino_acid),
    COALESCE(NULLIF(BTRIM(s.protein_description), ''), ''),
    BTRIM(s.gene_name),
    v_batch_id
  FROM ptm.stg_gs_ptm s
  WHERE NULLIF(BTRIM(s.ptm_types), '') IS NOT NULL
    AND UPPER(BTRIM(s.ptm_types)) <> 'DA'
    AND NULLIF(BTRIM(s.gene_name), '') IS NOT NULL
    AND s.position IS NOT NULL
    AND s.position > 0
    AND NULLIF(BTRIM(s.amino_acid), '') IS NOT NULL
  ON CONFLICT (
    organism,
    ptm_types,
    protein_accession,
    position,
    amino_acid,
    gene_name
  ) DO UPDATE
  SET protein_description = EXCLUDED.protein_description,
      source_batch_id = EXCLUDED.source_batch_id;

  RETURN v_batch_id;
END;
$$;
