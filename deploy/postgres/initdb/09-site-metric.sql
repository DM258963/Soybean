\set ON_ERROR_STOP on
\connect ptm_prod

CREATE SCHEMA IF NOT EXISTS ptm;

CREATE TABLE IF NOT EXISTS ptm.site_metric (
  metric_key TEXT PRIMARY KEY,
  metric_value BIGINT NOT NULL DEFAULT 0 CHECK (metric_value >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
