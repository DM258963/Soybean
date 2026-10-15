\set ON_ERROR_STOP on
\connect ptm_prod

SET search_path TO ptm, public;

ALTER TABLE ptm.gs_ptm DROP CONSTRAINT IF EXISTS gs_ptm_position_check;
ALTER TABLE ptm.gs_ptm
  ADD CONSTRAINT gs_ptm_position_check
  CHECK (position > 0);

ALTER TABLE ptm.gs_ptm DROP CONSTRAINT IF EXISTS gs_ptm_ptm_types_not_da_check;
ALTER TABLE ptm.gs_ptm
  ADD CONSTRAINT gs_ptm_ptm_types_not_da_check
  CHECK (UPPER(BTRIM(ptm_types)) <> 'DA');

ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w4m_1 DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w4m_2 DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w4m_3 DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w12m_1 DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w12m_2 DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w12m_3 DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w12m_w4m_ratio DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w12m_w4m_p_value DOUBLE PRECISION;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS w12m_w4m_type TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS subcellular_localization TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS record_type TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS transcript_id TEXT NOT NULL DEFAULT '';
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS gene_names TEXT NOT NULL DEFAULT '';
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kegg_ko_no TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kegg_gene TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kegg_pathway TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS biological_process TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS cellular_component TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS molecular_function TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS pfam_id TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS domain_description TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS site_domain TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kog_category TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kog_no TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kog_description TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS kegg_ko_no_2 TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS cog_category TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS cog_no TEXT;
ALTER TABLE ptm.gs_ptm ADD COLUMN IF NOT EXISTS cog_description TEXT;

CREATE INDEX IF NOT EXISTS idx_gs_ptm_w12m_w4m_type ON ptm.gs_ptm(w12m_w4m_type);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_transcript_id ON ptm.gs_ptm(transcript_id);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_gene_names ON ptm.gs_ptm(gene_names);

CREATE TABLE IF NOT EXISTS ptm.identifier_lookup (
  identifier_norm TEXT NOT NULL,
  identifier_raw TEXT NOT NULL,
  identifier_type TEXT NOT NULL,
  identifier_priority INT NOT NULL,
  organism TEXT NOT NULL DEFAULT '',
  gene_name TEXT NOT NULL DEFAULT '',
  protein_accession TEXT NOT NULL DEFAULT '',
  transcript_id TEXT NOT NULL DEFAULT '',
  gene_names TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_identifier_lookup_norm_priority
  ON ptm.identifier_lookup(identifier_norm, identifier_priority);
CREATE INDEX IF NOT EXISTS idx_identifier_lookup_target
  ON ptm.identifier_lookup(organism, protein_accession, gene_name);

CREATE OR REPLACE FUNCTION ptm.normalize_identifier(p_value TEXT)
RETURNS TEXT
LANGUAGE SQL
IMMUTABLE
AS $$
  SELECT REGEXP_REPLACE(LOWER(COALESCE(p_value, '')), '[^a-z0-9]', '', 'g');
$$;

CREATE OR REPLACE FUNCTION ptm.refresh_identifier_lookup()
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
  v_count BIGINT;
BEGIN
  TRUNCATE TABLE ptm.identifier_lookup;

  WITH proteins AS (
    SELECT DISTINCT
      COALESCE(NULLIF(BTRIM(organism), ''), '') AS organism,
      COALESCE(NULLIF(BTRIM(gene_name), ''), '') AS gene_name,
      COALESCE(NULLIF(BTRIM(protein_accession), ''), '') AS protein_accession,
      COALESCE(NULLIF(BTRIM(transcript_id), ''), '') AS transcript_id,
      COALESCE(NULLIF(BTRIM(gene_names), ''), '') AS gene_names
    FROM ptm.gs_ptm
    WHERE NULLIF(BTRIM(gene_name), '') IS NOT NULL
       OR NULLIF(BTRIM(protein_accession), '') IS NOT NULL
       OR NULLIF(BTRIM(transcript_id), '') IS NOT NULL
       OR NULLIF(BTRIM(gene_names), '') IS NOT NULL
  ),
  raw_identifiers AS (
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'transcript_id' AS identifier_type, 0 AS identifier_priority, transcript_id AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(transcript_id), '') IS NOT NULL

    UNION ALL
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'transcript_id' AS identifier_type, 0 AS identifier_priority, REGEXP_REPLACE(transcript_id, '[.]p$', '', 'i') AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(transcript_id), '') IS NOT NULL
      AND REGEXP_REPLACE(transcript_id, '[.]p$', '', 'i') <> transcript_id

    UNION ALL
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'gene_name' AS identifier_type, 1 AS identifier_priority, gene_name AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(gene_name), '') IS NOT NULL

    UNION ALL
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'protein_accession' AS identifier_type, 2 AS identifier_priority, protein_accession AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(protein_accession), '') IS NOT NULL

    UNION ALL
    SELECT p.organism, p.gene_name, p.protein_accession, p.transcript_id, p.gene_names,
           'gene_names' AS identifier_type, 3 AS identifier_priority, tok AS identifier_raw
    FROM proteins p
    CROSS JOIN LATERAL regexp_split_to_table(p.gene_names, '[[:space:],;|/]+') AS tok
    WHERE NULLIF(BTRIM(tok), '') IS NOT NULL
  ),
  normalized_identifiers AS (
    SELECT
      organism,
      gene_name,
      protein_accession,
      transcript_id,
      gene_names,
      identifier_type,
      identifier_priority,
      BTRIM(identifier_raw) AS identifier_raw,
      ptm.normalize_identifier(identifier_raw) AS identifier_norm
    FROM raw_identifiers
    WHERE NULLIF(BTRIM(identifier_raw), '') IS NOT NULL
  ),
  expanded_identifiers AS (
    SELECT * FROM normalized_identifiers
    WHERE identifier_norm <> ''

    UNION ALL
    SELECT
      organism,
      gene_name,
      protein_accession,
      transcript_id,
      gene_names,
      identifier_type,
      identifier_priority,
      identifier_raw,
      REGEXP_REPLACE(identifier_norm, '^glyma', '') AS identifier_norm
    FROM normalized_identifiers
    WHERE identifier_norm LIKE 'glyma%'
      AND LENGTH(REGEXP_REPLACE(identifier_norm, '^glyma', '')) >= 4
  )
  INSERT INTO ptm.identifier_lookup (
    identifier_norm,
    identifier_raw,
    identifier_type,
    identifier_priority,
    organism,
    gene_name,
    protein_accession,
    transcript_id,
    gene_names
  )
  SELECT DISTINCT
    identifier_norm,
    identifier_raw,
    identifier_type,
    identifier_priority,
    organism,
    gene_name,
    protein_accession,
    transcript_id,
    gene_names
  FROM expanded_identifiers
  WHERE identifier_norm <> '';

  GET DIAGNOSTICS v_count = ROW_COUNT;
  RETURN v_count;
END;
$$;

ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w4m_1 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w4m_2 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w4m_3 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w12m_1 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w12m_2 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w12m_3 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w12m_w4m_ratio TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w12m_w4m_p_value TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS w12m_w4m_type TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS subcellular_localization TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS record_type TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS transcript_id TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS gene_names TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kegg_ko_no TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kegg_gene TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kegg_pathway TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS biological_process TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS cellular_component TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS molecular_function TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS pfam_id TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS domain_description TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS site_domain TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kog_category TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kog_no TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kog_description TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS kegg_ko_no_2 TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS cog_category TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS cog_no TEXT;
ALTER TABLE ptm.stg_gs_ptm ADD COLUMN IF NOT EXISTS cog_description TEXT;

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

  PERFORM ptm.refresh_identifier_lookup();

  RETURN v_batch_id;
END;
$$;
