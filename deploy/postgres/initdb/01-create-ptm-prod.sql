\set ON_ERROR_STOP on

SELECT 'CREATE DATABASE ptm_prod'
WHERE NOT EXISTS (
  SELECT 1 FROM pg_database WHERE datname = 'ptm_prod'
)\gexec
