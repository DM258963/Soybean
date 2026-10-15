# Soybean PTM Viewer 1.0 (FastAPI Frontend)

## Run

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`.

## Configuration

Runtime configuration can be managed from a project-root `.env` file:

```bash
copy .env.example .env
```

Edit `.env` before starting the app or Docker services. Existing system
environment variables take precedence over values in `.env`.

Common settings:

- `HERMES_ASSISTANT_ENABLED=true` enables the Soybean Assistant.
- `HERMES_ASSISTANT_ENABLED=false` hides the assistant and disables `/api/hermes/*`.
- `PTM_DOWNLOADS_ENABLED=false` hides download/export buttons and disables Raw Data preview.
- `PTM_DOWNLOADS_ENABLED=true` restores download/export buttons and Raw Data preview.
- `PTM_AUTH_ENABLED=true` enables login and tester download permissions.
- `PTM_AUTH_SESSION_DAYS=30` keeps the same browser logged in for 30 days.
- `PTM_AUTH_MAX_FAILED_ATTEMPTS=5` locks an account after 5 failed logins.
- `PTM_AUTH_LOCKOUT_MINUTES=30` keeps the account locked for 30 minutes.
- `PTM_BOOTSTRAP_ADMIN_USERNAME=admin`
- `PTM_BOOTSTRAP_ADMIN_PASSWORD=...` creates the first admin user if it does not already exist.
- `PTM_DB_HOST=127.0.0.1`
- `PTM_DB_PORT=5432`
- `PTM_DB_NAME=ptm_prod`
- `PTM_DB_USER=myuser`
- `PTM_DB_PASSWORD=wowangle`

After changing `.env`, restart the Python app. If PostgreSQL settings used by
Docker changed, also restart the Compose service:

```bash
docker compose up -d postgres
```

## Protein Search Data Source

`/search/protein` now reads from PostgreSQL tables instead of local xlsx files:

- `ptm.gs_ptm`
- `ptm.protein_sequence`

Default DB connection used by `app.py`:

- `PTM_DB_SERVICE=postgres`
- `PTM_DB_NAME=ptm_prod`
- `PTM_DB_USER=myuser`

You can override them in `.env` or with system environment variables before
starting the app.

## Import CSV To DB

Protein CSV should include `Gene name` and `Protein` columns (order can be either one).

If your `ptm_prod` is already created, run this migration once to add/align `gene_name` relation:

```bash
docker compose exec -T postgres psql -U myuser -d ptm_prod -f /docker-entrypoint-initdb.d/05-migrate-protein-gene-name.sql
```

To enable the homepage visit counter on an existing database, run this migration once:

```bash
docker compose exec -T postgres psql -U myuser -d ptm_prod -f /docker-entrypoint-initdb.d/09-site-metric.sql
```

To enable login/user management tables on an existing database, run this migration once:

```bash
docker compose exec -T postgres psql -U myuser -d ptm_prod -f /docker-entrypoint-initdb.d/10-auth-users.sql
```

After login is enabled, use `/login` to sign in and `/admin/users` to create, update, or delete tester
accounts. Keep `PTM_DOWNLOADS_ENABLED=false` before publication; tester accounts with `Allow downloads`
checked can still preview Raw Data and use all download buttons after signing in. If a user enters the
wrong password too many times, the account is locked temporarily; saving that user in `/admin/users`
clears the lock. Password fields in user management include a `Show` option so newly created passwords
can be checked before saving.

```bash
# import both GS and protein sequence
python .\数据处理\import_ptm_csv.py --gs-csv .\gs_source_utf8.csv --protein-csv .\protein_sequence_utf8.csv

# import only GS
python .\数据处理\import_ptm_csv.py --gs-csv .\gs_source_utf8.csv

# import only protein sequence
python .\数据处理\import_ptm_csv.py --protein-csv .\protein_sequence_utf8.csv
```

## Structure

- `app.py`: FastAPI app, routes, and DB-backed search logic.
- `数据处理/import_ptm_csv.py`: CSV import helper script for PostgreSQL.
- `soybean_app/web/templates/protein_search.html`: Protein Search page.
- `deploy/postgres/initdb/*.sql`: database schema and import functions.
