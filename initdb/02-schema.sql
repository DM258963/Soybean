\set ON_ERROR_STOP on
\connect ptm_prod

CREATE SCHEMA IF NOT EXISTS ptm;

SET search_path TO ptm, public;

CREATE TABLE IF NOT EXISTS ptm.import_batch (
  batch_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  source_type TEXT NOT NULL CHECK (source_type IN ('protein_sequence', 'gs')),
  source_name TEXT NOT NULL,
  source_version TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- From protein sequence source (columns: Gene name, Protein)
CREATE TABLE IF NOT EXISTS ptm.protein_sequence (
  id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  protein TEXT NOT NULL,
  gene_name TEXT NOT NULL UNIQUE,
  seq_length INT GENERATED ALWAYS AS (char_length(protein)) STORED,
  source_batch_id BIGINT REFERENCES ptm.import_batch(batch_id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- From GS source columns
CREATE TABLE IF NOT EXISTS ptm.gs_ptm (
  organism TEXT NOT NULL,
  ptm_types TEXT NOT NULL CHECK (UPPER(BTRIM(ptm_types)) <> 'DA'),
  protein_accession TEXT NOT NULL,
  position INT NOT NULL CHECK (position > 0),
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

CREATE INDEX IF NOT EXISTS idx_gs_ptm_accession ON ptm.gs_ptm(protein_accession);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_gene_name ON ptm.gs_ptm(gene_name);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_transcript_id ON ptm.gs_ptm(transcript_id);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_gene_names ON ptm.gs_ptm(gene_names);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_organism ON ptm.gs_ptm(organism);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_position ON ptm.gs_ptm(position);
CREATE INDEX IF NOT EXISTS idx_gs_ptm_w12m_w4m_type ON ptm.gs_ptm(w12m_w4m_type);
CREATE INDEX IF NOT EXISTS idx_protein_sequence_gene_name ON ptm.protein_sequence(gene_name);
