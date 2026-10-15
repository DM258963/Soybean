\set ON_ERROR_STOP on
\connect ptm_prod

SET search_path TO ptm, public;

-- PTM code dictionary keyed by GS column "PTM types"
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
