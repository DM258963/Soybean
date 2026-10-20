\set ON_ERROR_STOP on
\connect ptm_prod

CREATE SCHEMA IF NOT EXISTS ptm;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

SET search_path TO ptm, public;

CREATE TABLE IF NOT EXISTS ptm.import_batch (
  batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_type TEXT NOT NULL CHECK (source_type IN ('protein_sequence', 'gs')),
  source_name TEXT NOT NULL,
  source_version TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ptm.protein_sequence (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  protein TEXT NOT NULL,
  gene_name TEXT NOT NULL UNIQUE,
  seq_length INT GENERATED ALWAYS AS (char_length(protein)) STORED,
  source_batch_id BIGINT REFERENCES ptm.import_batch(batch_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ptm.ptm_type_dict (
  ptm_types TEXT PRIMARY KEY,
  full_name TEXT,
  notes TEXT
);

INSERT INTO ptm.ptm_type_dict (ptm_types, full_name, notes)
VALUES
  ('ST', 'Phosphorylation (S/T)', 'From UI PTM style dictionary'),
  ('Ub', 'Lys ubiquitination', 'From UI PTM style dictionary'),
  ('Ac', 'Lys acetylation', 'From UI PTM style dictionary'),
  ('SNO', 'S-nitrosylation', 'From UI PTM style dictionary'),
  ('OX', 'Methionine oxidation', 'From UI PTM style dictionary'),
  ('DLa', 'D-lactylation', 'From UI PTM style dictionary'),
  ('LLa', 'L-lactylation', 'From UI PTM style dictionary'),
  ('Cr', 'Crotonylation', 'From UI PTM style dictionary'),
  ('Sc', 'Succinylation', 'From UI PTM style dictionary'),
  ('Sg', 'Succinylglycine', 'From UI PTM style dictionary'),
  ('Ss', 'Sulfurylation', 'From UI PTM style dictionary'),
  ('IOg', 'O-glycosylation', 'From UI PTM style dictionary'),
  ('3o', '3-oxo modification', 'From UI PTM style dictionary')
ON CONFLICT (ptm_types) DO UPDATE
SET full_name = EXCLUDED.full_name,
    notes = EXCLUDED.notes;

CREATE TABLE IF NOT EXISTS ptm.gs_ptm (
  organism TEXT NOT NULL,
  ptm_types TEXT NOT NULL,
  protein_accession TEXT NOT NULL,
  position INT NOT NULL,
  amino_acid TEXT NOT NULL,
  protein_description TEXT NOT NULL DEFAULT '',
  gene_name TEXT NOT NULL DEFAULT '',
  transcript_id TEXT NOT NULL DEFAULT '',
  gene_names TEXT NOT NULL DEFAULT '',
  record_type TEXT,
  w4m_1 DOUBLE PRECISION,
  w4m_2 DOUBLE PRECISION,
  w4m_3 DOUBLE PRECISION,
  w12m_1 DOUBLE PRECISION,
  w12m_2 DOUBLE PRECISION,
  w12m_3 DOUBLE PRECISION,
  w12m_w4m_ratio DOUBLE PRECISION,
  w12m_w4m_p_value DOUBLE PRECISION,
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
  cog_description TEXT,
  fmin_0based INT GENERATED ALWAYS AS (position - 1) STORED,
  fmax_0based INT GENERATED ALWAYS AS (position) STORED,
  source_batch_id BIGINT REFERENCES ptm.import_batch(batch_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (
    organism,
    ptm_types,
    protein_accession,
    position,
    amino_acid,
    gene_name
  )
);

-- Keep only the current constraints when this script is reapplied to an
-- existing database that may contain constraints from an older schema.
ALTER TABLE ptm.gs_ptm DROP CONSTRAINT IF EXISTS gs_ptm_check;
ALTER TABLE ptm.gs_ptm DROP CONSTRAINT IF EXISTS gs_ptm_position_check;
ALTER TABLE ptm.gs_ptm DROP CONSTRAINT IF EXISTS gs_ptm_ptm_types_check;
ALTER TABLE ptm.gs_ptm DROP CONSTRAINT IF EXISTS gs_ptm_ptm_types_not_da_check;
ALTER TABLE ptm.gs_ptm
  ADD CONSTRAINT gs_ptm_position_check CHECK (position > 0);
ALTER TABLE ptm.gs_ptm
  ADD CONSTRAINT gs_ptm_ptm_types_not_da_check
  CHECK (UPPER(BTRIM(ptm_types)) <> 'DA');

CREATE INDEX IF NOT EXISTS idx_gs_ptm_accession
  ON ptm.gs_ptm(protein_accession);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_gene_name
  ON ptm.gs_ptm(gene_name);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_transcript_id
  ON ptm.gs_ptm(transcript_id);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_gene_names
  ON ptm.gs_ptm(gene_names);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_organism
  ON ptm.gs_ptm(organism);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_position
  ON ptm.gs_ptm(position);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_w12m_w4m_type
  ON ptm.gs_ptm(w12m_w4m_type);

-- The UNIQUE constraint on gene_name already provides a B-tree index.
DROP INDEX IF EXISTS ptm.idx_protein_sequence_gene_name;

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
           'transcript_id' AS identifier_type, 0 AS identifier_priority,
           transcript_id AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(transcript_id), '') IS NOT NULL

    UNION ALL
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'transcript_id' AS identifier_type, 0 AS identifier_priority,
           REGEXP_REPLACE(transcript_id, '[.]p$', '', 'i') AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(transcript_id), '') IS NOT NULL
      AND REGEXP_REPLACE(transcript_id, '[.]p$', '', 'i') <> transcript_id

    UNION ALL
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'gene_name' AS identifier_type, 1 AS identifier_priority,
           gene_name AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(gene_name), '') IS NOT NULL

    UNION ALL
    SELECT organism, gene_name, protein_accession, transcript_id, gene_names,
           'protein_accession' AS identifier_type, 2 AS identifier_priority,
           protein_accession AS identifier_raw
    FROM proteins
    WHERE NULLIF(BTRIM(protein_accession), '') IS NOT NULL

    UNION ALL
    SELECT p.organism, p.gene_name, p.protein_accession, p.transcript_id, p.gene_names,
           'gene_names' AS identifier_type, 3 AS identifier_priority,
           tok AS identifier_raw
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

CREATE TABLE IF NOT EXISTS ptm.site_metric (
  metric_key TEXT PRIMARY KEY,
  metric_value BIGINT NOT NULL DEFAULT 0 CHECK (metric_value >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ptm.app_user (
  user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'tester' CHECK (role IN ('admin', 'tester')),
  can_download BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  failed_login_count INT NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  session_version BIGINT NOT NULL DEFAULT 1,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ptm.app_user
  ADD COLUMN IF NOT EXISTS failed_login_count INT NOT NULL DEFAULT 0;
ALTER TABLE ptm.app_user
  ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
ALTER TABLE ptm.app_user
  ADD COLUMN IF NOT EXISTS session_version BIGINT NOT NULL DEFAULT 1;

CREATE UNIQUE INDEX IF NOT EXISTS app_user_username_ci_unique
  ON ptm.app_user(LOWER(username));

CREATE TABLE IF NOT EXISTS ptm.auth_audit_log (
  audit_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  event_type TEXT NOT NULL,
  success BOOLEAN NOT NULL,
  actor_user_id BIGINT,
  target_user_id BIGINT,
  username TEXT,
  client_ip TEXT,
  user_agent TEXT,
  detail TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS auth_audit_log_created_at_idx
  ON ptm.auth_audit_log(created_at DESC);

CREATE TABLE IF NOT EXISTS ptm.user_agent_model_profile (
  user_id BIGINT NOT NULL
    REFERENCES ptm.app_user(user_id) ON DELETE CASCADE,
  mode TEXT NOT NULL CHECK (mode IN ('local', 'api')),
  provider TEXT NOT NULL CHECK (provider IN ('openai', 'groq', 'openai_compatible')),
  base_url TEXT NOT NULL,
  model_name TEXT NOT NULL,
  api_key_cipher BYTEA,
  llm_timeout DOUBLE PRECISION NOT NULL DEFAULT 30
    CHECK (llm_timeout >= 1 AND llm_timeout <= 300),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, mode)
);

CREATE TABLE IF NOT EXISTS ptm.user_agent_runtime_preference (
  user_id BIGINT PRIMARY KEY
    REFERENCES ptm.app_user(user_id) ON DELETE CASCADE,
  active_mode TEXT NOT NULL CHECK (active_mode IN ('local', 'api')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
