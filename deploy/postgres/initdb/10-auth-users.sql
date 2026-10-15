\set ON_ERROR_STOP on
\connect ptm_prod

CREATE SCHEMA IF NOT EXISTS ptm;

CREATE TABLE IF NOT EXISTS ptm.app_user (
  user_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'tester' CHECK (role IN ('admin', 'tester')),
  can_download BOOLEAN NOT NULL DEFAULT TRUE,
  is_active BOOLEAN NOT NULL DEFAULT TRUE,
  failed_login_count INT NOT NULL DEFAULT 0,
  locked_until TIMESTAMPTZ,
  last_login_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ptm.app_user
  ADD COLUMN IF NOT EXISTS failed_login_count INT NOT NULL DEFAULT 0;

ALTER TABLE ptm.app_user
  ADD COLUMN IF NOT EXISTS locked_until TIMESTAMPTZ;
