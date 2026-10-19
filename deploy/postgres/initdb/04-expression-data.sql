\set ON_ERROR_STOP on
\connect ptm_prod

CREATE SCHEMA IF NOT EXISTS ptm;

CREATE TABLE IF NOT EXISTS ptm.expression_dataset (
  dataset_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_key TEXT NOT NULL UNIQUE,
  dataset_name TEXT NOT NULL,
  organism TEXT NOT NULL,
  source_file TEXT NOT NULL,
  source_sheet TEXT NOT NULL,
  source_sha256 CHAR(64) NOT NULL,
  protein_count INT NOT NULL DEFAULT 0 CHECK (protein_count >= 0),
  measurement_count INT NOT NULL DEFAULT 0 CHECK (measurement_count >= 0),
  imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ptm.expression_protein (
  expression_protein_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  dataset_id BIGINT NOT NULL
    REFERENCES ptm.expression_dataset(dataset_id) ON DELETE CASCADE,
  protein_accession TEXT NOT NULL,
  gene_name TEXT NOT NULL DEFAULT '',
  protein_description TEXT NOT NULL DEFAULT '',
  UNIQUE (dataset_id, protein_accession)
);

CREATE TABLE IF NOT EXISTS ptm.expression_measurement (
  expression_protein_id BIGINT NOT NULL
    REFERENCES ptm.expression_protein(expression_protein_id) ON DELETE CASCADE,
  timepoint TEXT NOT NULL CHECK (timepoint ~ '^W[0-9]+$'),
  replicate_no SMALLINT NOT NULL CHECK (replicate_no > 0),
  abundance DOUBLE PRECISION NOT NULL,
  PRIMARY KEY (expression_protein_id, timepoint, replicate_no)
);

CREATE INDEX IF NOT EXISTS expression_protein_accession_ci_idx
  ON ptm.expression_protein(dataset_id, LOWER(protein_accession));

CREATE INDEX IF NOT EXISTS expression_protein_gene_name_ci_idx
  ON ptm.expression_protein(dataset_id, LOWER(gene_name));

CREATE INDEX IF NOT EXISTS expression_measurement_timepoint_idx
  ON ptm.expression_measurement(timepoint);

-- The UNIQUE constraint on (dataset_id, protein_accession) already covers
-- lookups by dataset_id alone.
DROP INDEX IF EXISTS ptm.expression_protein_dataset_idx;

COMMENT ON TABLE ptm.expression_dataset IS
  'One row per imported quantitative proteome workbook.';

COMMENT ON TABLE ptm.expression_protein IS
  'Protein metadata from a quantitative proteome dataset.';

COMMENT ON TABLE ptm.expression_measurement IS
  'One abundance value per protein, timepoint, and biological replicate.';
