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
  ON ptm.app_user (LOWER(username));

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
  ON ptm.auth_audit_log (created_at DESC);
