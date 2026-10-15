\set ON_ERROR_STOP on
\connect ptm_prod

SET search_path TO ptm, public;

-- Staging table for GS data source
CREATE TABLE IF NOT EXISTS ptm.stg_gs_ptm (
  organism TEXT,
  ptm_types TEXT,
  protein_accession TEXT,
  position INT,
  amino_acid TEXT,
  protein_description TEXT,
  gene_name TEXT,
  transcript_id TEXT,
  gene_names TEXT,
  record_type TEXT,
  w4m_1 TEXT,
  w4m_2 TEXT,
  w4m_3 TEXT,
  w12m_1 TEXT,
  w12m_2 TEXT,
  w12m_3 TEXT,
  w12m_w4m_ratio TEXT,
  w12m_w4m_p_value TEXT,
  w12m_w4m_type TEXT,
  subcellular_localization TEXT,
  kegg_ko_no TEXT,
  kegg_gene TEXT,
  kegg_pathway TEXT,
  biological_process TEXT,
  cellular_component TEXT,
  molecular_function TEXT,
  pfam_id TEXT,
  domain_description TEXT,
  site_domain TEXT,
  kog_category TEXT,
  kog_no TEXT,
  kog_description TEXT,
  kegg_ko_no_2 TEXT,
  cog_category TEXT,
  cog_no TEXT,
  cog_description TEXT
);

-- Staging table for protein sequence source (Gene name + Protein)
CREATE TABLE IF NOT EXISTS ptm.stg_protein_sequence (
  protein TEXT,
  gene_name TEXT
);

CREATE OR REPLACE PROCEDURE ptm.clear_staging()
LANGUAGE plpgsql
AS $$
BEGIN
  TRUNCATE TABLE ptm.stg_gs_ptm;
  TRUNCATE TABLE ptm.stg_protein_sequence;
END;
$$;

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

  WITH dedup AS (
    SELECT DISTINCT ON (
      COALESCE(NULLIF(BTRIM(s.organism), ''), 'Unknown'),
      BTRIM(s.ptm_types),
      COALESCE(NULLIF(BTRIM(s.protein_accession), ''), 'Unknown'),
      s.position,
      BTRIM(s.amino_acid),
      BTRIM(s.gene_name)
    )
    COALESCE(NULLIF(BTRIM(s.organism), ''), 'Unknown') AS organism,
    BTRIM(s.ptm_types) AS ptm_types,
    COALESCE(NULLIF(BTRIM(s.protein_accession), ''), 'Unknown') AS protein_accession,
    s.position AS position,
    BTRIM(s.amino_acid) AS amino_acid,
    COALESCE(NULLIF(BTRIM(s.protein_description), ''), '') AS protein_description,
    BTRIM(s.gene_name) AS gene_name,
    COALESCE(NULLIF(BTRIM(s.transcript_id), ''), '') AS transcript_id,
    COALESCE(NULLIF(BTRIM(s.gene_names), ''), '') AS gene_names,
    NULLIF(BTRIM(s.record_type), '') AS record_type,
    CASE WHEN NULLIF(BTRIM(s.w4m_1), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w4m_1)::DOUBLE PRECISION ELSE NULL END AS w4m_1,
    CASE WHEN NULLIF(BTRIM(s.w4m_2), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w4m_2)::DOUBLE PRECISION ELSE NULL END AS w4m_2,
    CASE WHEN NULLIF(BTRIM(s.w4m_3), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w4m_3)::DOUBLE PRECISION ELSE NULL END AS w4m_3,
    CASE WHEN NULLIF(BTRIM(s.w12m_1), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w12m_1)::DOUBLE PRECISION ELSE NULL END AS w12m_1,
    CASE WHEN NULLIF(BTRIM(s.w12m_2), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w12m_2)::DOUBLE PRECISION ELSE NULL END AS w12m_2,
    CASE WHEN NULLIF(BTRIM(s.w12m_3), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w12m_3)::DOUBLE PRECISION ELSE NULL END AS w12m_3,
    CASE WHEN NULLIF(BTRIM(s.w12m_w4m_ratio), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w12m_w4m_ratio)::DOUBLE PRECISION ELSE NULL END AS w12m_w4m_ratio,
    CASE WHEN NULLIF(BTRIM(s.w12m_w4m_p_value), '') ~ '^[+-]?(([0-9]+([.][0-9]*)?)|([.][0-9]+))([eE][+-]?[0-9]+)?$' THEN BTRIM(s.w12m_w4m_p_value)::DOUBLE PRECISION ELSE NULL END AS w12m_w4m_p_value,
    NULLIF(BTRIM(s.w12m_w4m_type), '') AS w12m_w4m_type,
    NULLIF(BTRIM(s.subcellular_localization), '') AS subcellular_localization,
    NULLIF(BTRIM(s.kegg_ko_no), '') AS kegg_ko_no,
    NULLIF(BTRIM(s.kegg_gene), '') AS kegg_gene,
    NULLIF(BTRIM(s.kegg_pathway), '') AS kegg_pathway,
    NULLIF(BTRIM(s.biological_process), '') AS biological_process,
    NULLIF(BTRIM(s.cellular_component), '') AS cellular_component,
    NULLIF(BTRIM(s.molecular_function), '') AS molecular_function,
    NULLIF(BTRIM(s.pfam_id), '') AS pfam_id,
    NULLIF(BTRIM(s.domain_description), '') AS domain_description,
    NULLIF(BTRIM(s.site_domain), '') AS site_domain,
    NULLIF(BTRIM(s.kog_category), '') AS kog_category,
    NULLIF(BTRIM(s.kog_no), '') AS kog_no,
    NULLIF(BTRIM(s.kog_description), '') AS kog_description,
    NULLIF(BTRIM(s.kegg_ko_no_2), '') AS kegg_ko_no_2,
    NULLIF(BTRIM(s.cog_category), '') AS cog_category,
    NULLIF(BTRIM(s.cog_no), '') AS cog_no,
    NULLIF(BTRIM(s.cog_description), '') AS cog_description
    FROM ptm.stg_gs_ptm s
    WHERE NULLIF(BTRIM(s.ptm_types), '') IS NOT NULL
      AND UPPER(BTRIM(s.ptm_types)) <> 'DA'
      AND NULLIF(BTRIM(s.gene_name), '') IS NOT NULL
      AND s.position IS NOT NULL
      AND s.position > 0
      AND NULLIF(BTRIM(s.amino_acid), '') IS NOT NULL
    ORDER BY
      COALESCE(NULLIF(BTRIM(s.organism), ''), 'Unknown'),
      BTRIM(s.ptm_types),
      COALESCE(NULLIF(BTRIM(s.protein_accession), ''), 'Unknown'),
      s.position,
      BTRIM(s.amino_acid),
      BTRIM(s.gene_name),
      s.ctid DESC
  )
  INSERT INTO ptm.gs_ptm (
    organism,
    ptm_types,
    protein_accession,
    position,
    amino_acid,
    protein_description,
    gene_name,
    transcript_id,
    gene_names,
    record_type,
    w4m_1,
    w4m_2,
    w4m_3,
    w12m_1,
    w12m_2,
    w12m_3,
    w12m_w4m_ratio,
    w12m_w4m_p_value,
    w12m_w4m_type,
    subcellular_localization,
    kegg_ko_no,
    kegg_gene,
    kegg_pathway,
    biological_process,
    cellular_component,
    molecular_function,
    pfam_id,
    domain_description,
    site_domain,
    kog_category,
    kog_no,
    kog_description,
    kegg_ko_no_2,
    cog_category,
    cog_no,
    cog_description,
    source_batch_id
  )
  SELECT
    d.organism,
    d.ptm_types,
    d.protein_accession,
    d.position,
    d.amino_acid,
    d.protein_description,
    d.gene_name,
    d.transcript_id,
    d.gene_names,
    d.record_type,
    d.w4m_1,
    d.w4m_2,
    d.w4m_3,
    d.w12m_1,
    d.w12m_2,
    d.w12m_3,
    d.w12m_w4m_ratio,
    d.w12m_w4m_p_value,
    d.w12m_w4m_type,
    d.subcellular_localization,
    d.kegg_ko_no,
    d.kegg_gene,
    d.kegg_pathway,
    d.biological_process,
    d.cellular_component,
    d.molecular_function,
    d.pfam_id,
    d.domain_description,
    d.site_domain,
    d.kog_category,
    d.kog_no,
    d.kog_description,
    d.kegg_ko_no_2,
    d.cog_category,
    d.cog_no,
    d.cog_description,
    v_batch_id
  FROM dedup d
  ON CONFLICT (
    organism,
    ptm_types,
    protein_accession,
    position,
    amino_acid,
    gene_name
  ) DO UPDATE
  SET protein_description = EXCLUDED.protein_description,
      transcript_id = EXCLUDED.transcript_id,
      gene_names = EXCLUDED.gene_names,
      w4m_1 = EXCLUDED.w4m_1,
      w4m_2 = EXCLUDED.w4m_2,
      w4m_3 = EXCLUDED.w4m_3,
      w12m_1 = EXCLUDED.w12m_1,
      w12m_2 = EXCLUDED.w12m_2,
      w12m_3 = EXCLUDED.w12m_3,
      w12m_w4m_ratio = EXCLUDED.w12m_w4m_ratio,
      w12m_w4m_p_value = EXCLUDED.w12m_w4m_p_value,
      w12m_w4m_type = EXCLUDED.w12m_w4m_type,
      record_type = EXCLUDED.record_type,
      subcellular_localization = EXCLUDED.subcellular_localization,
      kegg_ko_no = EXCLUDED.kegg_ko_no,
      kegg_gene = EXCLUDED.kegg_gene,
      kegg_pathway = EXCLUDED.kegg_pathway,
      biological_process = EXCLUDED.biological_process,
      cellular_component = EXCLUDED.cellular_component,
      molecular_function = EXCLUDED.molecular_function,
      pfam_id = EXCLUDED.pfam_id,
      domain_description = EXCLUDED.domain_description,
      site_domain = EXCLUDED.site_domain,
      kog_category = EXCLUDED.kog_category,
      kog_no = EXCLUDED.kog_no,
      kog_description = EXCLUDED.kog_description,
      kegg_ko_no_2 = EXCLUDED.kegg_ko_no_2,
      cog_category = EXCLUDED.cog_category,
      cog_no = EXCLUDED.cog_no,
      cog_description = EXCLUDED.cog_description,
      source_batch_id = EXCLUDED.source_batch_id;

  RETURN v_batch_id;
END;
$$;

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

-- Usage example:
-- 1) CALL ptm.clear_staging();
-- 2) \copy ptm.stg_gs_ptm FROM '/tmp/gs_source.csv' WITH (FORMAT csv, HEADER true)
-- 3) SELECT ptm.apply_stg_gs_ptm('gs_source', 'v1');
-- 4) \copy ptm.stg_protein_sequence (protein, gene_name) FROM '/tmp/protein_sequence.csv' WITH (FORMAT csv, HEADER true)
-- 5) SELECT ptm.apply_stg_protein_sequence('protein_sequence', 'v1');
