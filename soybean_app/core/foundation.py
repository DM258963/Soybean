import csv
import base64
import hashlib
import hmac
import io
import json
import math
import mimetypes
import os
import re
import queue
import shutil
import secrets
import ssl
import statistics
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterator

import uvicorn
from .env import load_project_env
from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_project_env()

try:
    import psycopg
    from psycopg import OperationalError
except Exception:
    psycopg = None
    OperationalError = RuntimeError

try:
    import certifi
except Exception:
    certifi = None

PACKAGE_DIR = Path(__file__).resolve().parents[1]
BASE_DIR = Path(os.getenv("PTM_BASE_DIR", str(PACKAGE_DIR.parent))).resolve()
WEB_DIR = PACKAGE_DIR / "web"
STATIC_DIR = WEB_DIR / "static"
TEMPLATE_DIR = WEB_DIR / "templates"

DB_CONFIG = {
    "service": os.getenv("PTM_DB_SERVICE", "postgres"),
    "host": os.getenv("PTM_DB_HOST", "127.0.0.1"),
    "port": int(os.getenv("PTM_DB_PORT", "5432")),
    "dbname": os.getenv("PTM_DB_NAME", "ptm_prod"),
    "user": os.getenv("PTM_DB_USER", "myuser"),
    "password": os.getenv("PTM_DB_PASSWORD", "wowangle"),
    "connect_timeout": int(os.getenv("PTM_DB_CONNECT_TIMEOUT", "5")),
    "pool_min_size": int(os.getenv("PTM_DB_POOL_MIN_SIZE", "1")),
    "pool_max_size": int(os.getenv("PTM_DB_POOL_MAX_SIZE", "8")),
}

SPECIES_OPTIONS = [
    {
        "value": "glycine_max",
        "label": "Glycine max",
        "display": "Glycine max",
        "terms": ["glycine max", "soybean"],
    },
    {
        "value": "bradyrhizobium_diazoefficiens",
        "label": "Bradyrhizobium diazoefficiens",
        "display": "Bradyrhizobium diazoefficiens",
        "terms": ["bradyrhizobium diazoefficiens", "bradyrhizobium", "diazoefficiens"],
    },
]
DEFAULT_SPECIES = SPECIES_OPTIONS[0]["value"]
SPECIES_IDENTIFIER_EXAMPLES = {
    "glycine_max": [
        {"label": "Gene name", "value": "GLYMA_10G142500"},
        {"label": "Accession", "value": "I1LAY3"},
        {"label": "Short ID", "value": "10G142500"},
    ],
    "bradyrhizobium_diazoefficiens": [
        {"label": "Gene name", "value": "rpoC"},
        {"label": "Accession", "value": "Q89J75"},
        {"label": "Gene name", "value": "nifD"},
    ],
}
PTM_SEARCH_MAX_RESULTS = int(os.getenv("PTM_SEARCH_MAX_RESULTS", "500"))
PTM_SEARCH_PAGE_SIZE_DEFAULT = int(os.getenv("PTM_SEARCH_PAGE_SIZE_DEFAULT", "50"))
PTM_SEARCH_PAGE_SIZE_OPTIONS = [25, 50, 100]
DATA_TABLE_PAGE_SIZE_DEFAULT = int(os.getenv("DATA_TABLE_PAGE_SIZE_DEFAULT", "50"))
DATA_TABLE_PAGE_SIZE_OPTIONS = [25, 50, 100]
IMPORT_READY_DIR = BASE_DIR / "data" / "import_ready"
EXPRESSION_DATASETS = {
    "glycine_max": {
        "path": BASE_DIR / "data" / "Dataset S1-Soybean-DA-mean.xlsx",
        "sheet": "Soybean protein quant",
        "label": "Dataset S1-Soybean-DA-mean",
        "display": "Soybean protein quant",
    },
    "bradyrhizobium_diazoefficiens": {
        "path": BASE_DIR / "data" / "Dataset S2-Rhizobia-DA-mean.xlsx",
        "sheet": "Rhizobia protein quant",
        "label": "Dataset S2-Rhizobia-DA-mean",
        "display": "Rhizobia protein quant",
    },
}
EXPRESSION_TIMEPOINTS = ["W2", "W4", "W6", "W8", "W10", "W12"]
BLAST_DB_DIR = BASE_DIR / "runtime" / "blastdb_cache"
BLAST_MAX_DB_SEQUENCES = int(os.getenv("PTM_BLAST_MAX_DB_SEQUENCES", "200000"))
BLAST_METADATA_SCOPE = "all_proteins_v1"
BLAST_DEFAULT_IDENTITY_MIN = float(os.getenv("PTM_BLAST_DEFAULT_IDENTITY_MIN", "30"))
BLAST_DEFAULT_E_VALUE_MAX = float(os.getenv("PTM_BLAST_DEFAULT_E_VALUE_MAX", "1e-5"))
BLAST_DEFAULT_QUERY_COVER_MIN = float(os.getenv("PTM_BLAST_DEFAULT_QUERY_COVER_MIN", "70"))
BLAST_DEFAULT_MAX_HITS = int(os.getenv("PTM_BLAST_DEFAULT_MAX_HITS", "20"))
HOME_DATA_TABLES = [
    {
        "filename": "soybean_gs.csv",
        "species": "Glycine max",
        "data_type": "PTM sites / GS data",
    },
    {
        "filename": "soybean_protein_sequence.csv",
        "species": "Glycine max",
        "data_type": "Protein sequences",
    },
    {
        "filename": "rhizobium_gs.csv",
        "species": "Bradyrhizobium diazoefficiens",
        "data_type": "PTM sites / GS data",
    },
    {
        "filename": "rhizobium_protein_sequence.csv",
        "species": "Bradyrhizobium diazoefficiens",
        "data_type": "Protein sequences",
    },
]


def normalize_species_key(value: str) -> str:
    selected = (value or "").strip().lower()
    allowed = {str(option["value"]) for option in SPECIES_OPTIONS}
    return selected if selected in allowed else DEFAULT_SPECIES


def get_species_option(value: str) -> dict[str, Any]:
    species_key = normalize_species_key(value)
    for option in SPECIES_OPTIONS:
        if option["value"] == species_key:
            return option
    return SPECIES_OPTIONS[0]


def build_species_sql_condition(value: str, table_prefix: str = "") -> str:
    option = get_species_option(value)
    column = f"{table_prefix}.organism" if table_prefix else "organism"
    terms = [str(term).strip().lower() for term in option.get("terms", []) if str(term).strip()]
    if not terms:
        return "TRUE"
    clauses = [f"LOWER(COALESCE({column}, '')) LIKE '%{term}%'" for term in terms]
    return "(" + " OR ".join(clauses) + ")"


def build_modification_sql_condition(column: str = "ptm_types") -> str:
    excluded = ", ".join(pg_quote(code.upper()) for code in NON_MODIFICATION_CLASSES)
    return f"(NULLIF(BTRIM({column}), '') IS NOT NULL AND UPPER(BTRIM({column})) NOT IN ({excluded}))"


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "ture", "yes", "y", "on"}


UNIPROT_TIMEOUT_SEC = float(os.getenv("PTM_UNIPROT_TIMEOUT_SEC", "10"))
UNIPROT_SSL_VERIFY = _env_bool("PTM_UNIPROT_SSL_VERIFY", True)
UNIPROT_CA_FILE = os.getenv("PTM_UNIPROT_CA_FILE", "").strip()
PTM_DOWNLOADS_ENABLED = _env_bool("PTM_DOWNLOADS_ENABLED", False)
DOWNLOADS_DISABLED_MESSAGE = "Downloads and raw data preview are temporarily unavailable before publication."
PTM_AUTH_ENABLED = _env_bool("PTM_AUTH_ENABLED", True)
PTM_AUTH_SECRET_KEY = os.getenv("PTM_AUTH_SECRET_KEY", "").strip()
PTM_AUTH_COOKIE_NAME = os.getenv("PTM_AUTH_COOKIE_NAME", "soybean_ptm_session")
PTM_AUTH_SESSION_DAYS = max(1, int(os.getenv("PTM_AUTH_SESSION_DAYS", "7")))
PTM_AUTH_COOKIE_SECURE = _env_bool("PTM_AUTH_COOKIE_SECURE", False)
PTM_AUTH_MAX_FAILED_ATTEMPTS = max(1, int(os.getenv("PTM_AUTH_MAX_FAILED_ATTEMPTS", "5")))
PTM_AUTH_LOCKOUT_MINUTES = max(1, int(os.getenv("PTM_AUTH_LOCKOUT_MINUTES", "30")))
PTM_AUTH_IP_MAX_FAILED_ATTEMPTS = max(1, int(os.getenv("PTM_AUTH_IP_MAX_FAILED_ATTEMPTS", "20")))
PTM_AUTH_IP_WINDOW_MINUTES = max(1, int(os.getenv("PTM_AUTH_IP_WINDOW_MINUTES", "15")))
PTM_AUTH_PASSWORD_MIN_LENGTH = max(10, int(os.getenv("PTM_AUTH_PASSWORD_MIN_LENGTH", "10")))
PTM_AUTH_PASSWORD_MAX_LENGTH = max(PTM_AUTH_PASSWORD_MIN_LENGTH, int(os.getenv("PTM_AUTH_PASSWORD_MAX_LENGTH", "256")))
PTM_AUTH_PBKDF2_ITERATIONS = max(260000, int(os.getenv("PTM_AUTH_PBKDF2_ITERATIONS", "600000")))
PTM_BOOTSTRAP_ADMIN_USERNAME = os.getenv("PTM_BOOTSTRAP_ADMIN_USERNAME", "admin").strip()
PTM_BOOTSTRAP_ADMIN_PASSWORD = os.getenv("PTM_BOOTSTRAP_ADMIN_PASSWORD", "").strip()


def validate_auth_security_config() -> None:
    if not PTM_AUTH_ENABLED:
        return
    if len(PTM_AUTH_SECRET_KEY) < 32 or PTM_AUTH_SECRET_KEY == "replace-with-a-long-random-secret":
        raise RuntimeError("PTM_AUTH_SECRET_KEY must be a unique random value of at least 32 characters.")


PTM_STYLE = {
    "Ub": {"tag": "ub", "label": "ubiquitylation(K)", "bg": "#f5da2f", "fg": "#c9211e"},
    "Ac": {"tag": "ac", "label": "Acetylation(K)", "bg": "#2f4ea9", "fg": "#ffe34a"},
    "ST": {"tag": "st", "label": "phosphorylation(S/T/Y)", "bg": "#e73b2f", "fg": "#ffffff"},
    "Sc": {"tag": "sc", "label": "succinylation(K)", "bg": "#258fc6", "fg": "#ffffff"},
    "Cr": {"tag": "cr", "label": "crotonylation(K)", "bg": "#7a5ec8", "fg": "#ffffff"},
    "3o": {"tag": "3o", "label": "β-hydroxybutyrylation(K)", "bg": "#c45a84", "fg": "#ffffff"},
    "LLa": {"tag": "lla", "label": "L-lactylation(K)", "bg": "#f6be6b", "fg": "#111111"},
    "DLa": {"tag": "dla", "label": "D-lactylation(K)", "bg": "#f09748", "fg": "#111111"},
    "Ig": {"tag": "ig", "label": "N-glycopeptide(N)", "bg": "#8e44ad", "fg": "#ffffff"},
    "IOg": {"tag": "iog", "label": "Intact O-GalNAc glycopeptide(S/T)", "bg": "#9a6d39", "fg": "#ffffff"},
    "Og": {"tag": "og", "label": "O-glycosylation(S/T)", "bg": "#b9770e", "fg": "#ffffff"},
    "Sn": {"tag": "sn", "label": "S-nitrosylation", "bg": "#d35454", "fg": "#ffffff"},
    "Sl": {"tag": "sl", "label": "Sulfenylation", "bg": "#1f9d8f", "fg": "#ffffff"},
    "Sg": {"tag": "sg", "label": "S-glutathionylation", "bg": "#20a08b", "fg": "#ffffff"},
    "Ss": {"tag": "ss", "label": "S-sulfhydration", "bg": "#5f7aa0", "fg": "#ffffff"},
}

PTM_PRIORITY = ["Ub", "Ac", "ST", "Sc", "Cr", "3o", "LLa", "DLa", "Ig", "IOg", "Og", "Sn", "Sl", "Sg", "Ss"]
NON_MODIFICATION_CLASSES = {"DA"}


def order_ptm_codes(ptm_codes: set[str]) -> list[str]:
    ordered = [ptm for ptm in PTM_PRIORITY if ptm in ptm_codes]
    remaining = sorted([ptm for ptm in ptm_codes if ptm not in ordered])
    return ordered + remaining


def is_visual_ptm_code(ptm_code: str) -> bool:
    code = str(ptm_code or "").strip()
    return bool(code) and code.upper() not in NON_MODIFICATION_CLASSES


def get_ptm_style(ptm_code: str) -> dict[str, str]:
    return PTM_STYLE.get(
        ptm_code,
        {"tag": ptm_code.lower()[:3] if ptm_code else "", "label": ptm_code or "Unknown PTM", "bg": "#e73b2f", "fg": "#ffffff"},
    )


def build_multi_ptm_background(ordered_codes: list[str]) -> str:
    if not ordered_codes:
        return ""
    if len(ordered_codes) == 1:
        return get_ptm_style(ordered_codes[0])["bg"]
    return "#000000"


def build_ptm_legend_from_sequence(sequence_rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    seen = set()
    has_multiple_types = False
    for line in sequence_rows:
        for cell in line.get("cells", []):
            if cell.get("highlight"):
                ptm_codes = cell.get("ptm_codes", [])
                if len(ptm_codes) > 1:
                    has_multiple_types = True
                for code in ptm_codes:
                    seen.add(code)

    legend_codes = order_ptm_codes(seen)

    legend_items = []
    for code in legend_codes:
        style = get_ptm_style(code)
        legend_items.append({"code": code, "label": style["label"], "bg": style["bg"], "fg": style["fg"]})
    if has_multiple_types:
        legend_items.append({"code": "__multiple__", "label": "Multiple types", "bg": "#000000", "fg": "#ffffff"})
    return legend_items

NAV_ITEMS = [
    {"key": "home", "label": "Home", "endpoint": "/"},
    {"key": "proteome", "label": "Proteome", "endpoint": "/proteome"},
    {"key": "ptm", "label": "PTM", "endpoint": "/search/protein"},
    {"key": "analysis", "label": "Analysis", "endpoint": "/analysis"},
    {"key": "browse", "label": "Browse", "endpoint": "/browse"},
    {"key": "data", "label": "Data", "endpoint": "/data/raw"},
    {"key": "about", "label": "About", "endpoint": "/about"},
]

SEARCH_MENU = [
    {"key": "search-protein", "label": "Protein", "endpoint": "/search/protein"},
    {"key": "search-ptm", "label": "PTM", "endpoint": "/search/ptm"},
]

ANALYSIS_MENU = [
    {"key": "analysis", "label": "List Analysis", "endpoint": "/analysis"},
]

DATA_MENU = [
    {"key": "data-raw", "label": "Raw Data", "endpoint": "/data/raw"},
    {"key": "data-submit", "label": "Submit Data", "endpoint": "/data/submit"},
]

PAGES = {
    "proteome": {
        "title": "Protein Expression Profiles",
        "subtitle": "Explore protein abundance across nodule stages.",
        "description": (
            "Search proteome-level expression profiles by identifier or sequence, "
            "then open a protein-level view of stage-specific abundance."
        ),
        "actions": ["Identifier Search", "Sequence Search", "Expression Profiles"],
    },
    "search": {
        "title": "Search",
        "subtitle": "Find proteins and PTMs with flexible filters.",
        "description": (
            "Use this module to query proteins, peptide features, and PTM patterns. "
            "You can start from a protein ID, keyword, sequence motif, or curated PTM type."
        ),
        "actions": ["Protein Search", "PTM Search", "Advanced Filters"],
    },
    "search-protein": {
        "title": "Protein Search",
        "subtitle": "Search proteins and view sequence-level PTM annotations.",
        "description": (
            "Submit protein identifiers, descriptions, or sequences to display PTM-rich "
            "protein overviews and domain-level annotations."
        ),
        "actions": ["Input Protein IDs", "Upload FASTA", "Open Example Query"],
    },
    "search-ptm": {
        "title": "PTM Search",
        "subtitle": "Find species-specific target motifs and potential PTM crosstalk sites.",
        "description": (
            "Run motif-oriented PTM queries to detect co-occurrence, sequence context "
            "constraints, and experimentally supported PTM patterns across supported species."
        ),
        "actions": ["Motif Query", "Crosstalk Query", "Domain-aware Query"],
    },
    "analysis": {
        "title": "Analysis",
        "subtitle": "Analyze enrichment and PTM distribution across lists.",
        "description": (
            "Perform list analysis for soybean protein lists and compare PTM-level "
            "enrichment, depletion, and pathway-oriented signals."
        ),
        "actions": ["List Analysis", "PTM Statistics", "Export Results"],
    },
    "browse": {
        "title": "Browse",
        "subtitle": "Browse curated soybean PTM records.",
        "description": (
            "Explore soybean PTM data by experiment type, publication source, "
            "and confidence level in an easy browsing workflow."
        ),
        "actions": ["By PTM Type", "By Publication", "By Confidence"],
    },
    "data-submit": {
        "title": "Submit Data",
        "subtitle": "Contribute new soybean PTM studies to the community database.",
        "description": (
            "Upload peer-reviewed PTM datasets with metadata templates. "
            "The curation workflow helps keep records structured and reusable."
        ),
        "actions": ["Submission Guide", "Template Download", "Start Submission"],
    },
    "about": {
        "title": "About",
        "subtitle": "Project goals, design notes, and data policy.",
        "description": (
            "Soybean PTM Viewer 1.0 is a practical platform for sequence-centric PTM "
            "discovery, browsing, and systems-level analysis."
        ),
        "actions": ["Version Notes", "Citation", "Contact Team"],
    },
}


def pg_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class PgConnectionPool:
    def __init__(self, min_size: int, max_size: int) -> None:
        self.min_size = max(0, min_size)
        self.max_size = max(1, max_size)
        self._available: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=self.max_size)
        self._lock = threading.Lock()
        self._created = 0

        for _ in range(min(self.min_size, self.max_size)):
            self._available.put(self._create_connection())
            self._created += 1

    def _create_connection(self) -> Any:
        if psycopg is None:
            raise RuntimeError(
                "psycopg is required for database access. Install it with: pip install 'psycopg[binary]>=3.1,<4.0'"
            )
        return psycopg.connect(
            host=DB_CONFIG["host"],
            port=DB_CONFIG["port"],
            dbname=DB_CONFIG["dbname"],
            user=DB_CONFIG["user"],
            password=DB_CONFIG["password"],
            connect_timeout=DB_CONFIG["connect_timeout"],
            autocommit=True,
        )

    def _get(self) -> Any:
        try:
            conn = self._available.get_nowait()
        except queue.Empty:
            with self._lock:
                if self._created < self.max_size:
                    self._created += 1
                    should_create = True
                else:
                    should_create = False
            if should_create:
                try:
                    return self._create_connection()
                except Exception:
                    with self._lock:
                        self._created = max(0, self._created - 1)
                    raise
            conn = self._available.get()

        if getattr(conn, "closed", True):
            with self._lock:
                self._created = max(0, self._created - 1)
            return self._get()
        return conn

    def _put(self, conn: Any) -> None:
        if getattr(conn, "closed", True):
            with self._lock:
                self._created = max(0, self._created - 1)
            return

        try:
            self._available.put_nowait(conn)
        except queue.Full:
            conn.close()
            with self._lock:
                self._created = max(0, self._created - 1)

    def discard(self, conn: Any) -> None:
        try:
            conn.close()
        finally:
            with self._lock:
                self._created = max(0, self._created - 1)

    @contextmanager
    def connection(self) -> Iterator[Any]:
        conn = self._get()
        try:
            yield conn
        finally:
            self._put(conn)

    def closeall(self) -> None:
        while True:
            try:
                conn = self._available.get_nowait()
            except queue.Empty:
                break
            try:
                conn.close()
            except Exception:
                pass
        with self._lock:
            self._created = 0


_DB_POOL: PgConnectionPool | None = None
_DB_POOL_LOCK = threading.Lock()


def get_db_pool() -> PgConnectionPool:
    global _DB_POOL
    if _DB_POOL is None:
        with _DB_POOL_LOCK:
            if _DB_POOL is None:
                _DB_POOL = PgConnectionPool(
                    min_size=int(DB_CONFIG["pool_min_size"]),
                    max_size=int(DB_CONFIG["pool_max_size"]),
                )
    return _DB_POOL


def run_psql_csv_query(sql: str) -> list[dict[str, str]]:
    pool = get_db_pool()
    last_error: Exception | None = None

    for _ in range(2):
        conn = pool._get()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
                if cur.description is None:
                    pool._put(conn)
                    return []

                headers = [column.name for column in cur.description]
                rows = cur.fetchall()
                pool._put(conn)
                return [
                    {header: "" if value is None else str(value) for header, value in zip(headers, row)}
                    for row in rows
                ]
        except OperationalError as exc:
            last_error = exc
            pool.discard(conn)
        except Exception:
            pool._put(conn)
            raise

    raise RuntimeError(str(last_error) if last_error else "Database query failed")


def normalize_sequence_input(raw_sequence: str) -> str:
    lines = []
    for line in raw_sequence.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(">"):
            continue
        lines.append(stripped)
    return "".join("".join(lines).split()).upper()


def normalize_identifier_token(raw_value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", raw_value.strip().lower())


def split_gene_aliases(raw_gene_name: str) -> list[str]:
    if not raw_gene_name:
        return []
    tokens = re.split(r"[,\s;|/]+", raw_gene_name.strip())
    output: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        value = token.strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(value)
    return output


@lru_cache(maxsize=32)
def table_has_column(table_name: str, column_name: str) -> bool:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table_name):
        return False
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", column_name):
        return False

    rows = run_psql_csv_query(
        f"""
        SELECT 1 AS present
        FROM information_schema.columns
        WHERE table_schema = 'ptm'
          AND table_name = {pg_quote(table_name)}
          AND column_name = {pg_quote(column_name)}
        LIMIT 1;
        """
    )
    return bool(rows)


@lru_cache(maxsize=32)
def table_exists(table_name: str) -> bool:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", table_name):
        return False

    rows = run_psql_csv_query(
        f"""
        SELECT 1 AS present
        FROM information_schema.tables
        WHERE table_schema = 'ptm'
          AND table_name = {pg_quote(table_name)}
        LIMIT 1;
        """
    )
    return bool(rows)


def get_gs_identifier_columns() -> list[str]:
    columns: list[str] = []
    for column in ("transcript_id", "gene_name", "protein_accession", "gene_names"):
        if column in {"gene_name", "protein_accession"} or table_has_column("gs_ptm", column):
            columns.append(column)
    return columns


def build_gs_optional_identifier_select(table_prefix: str = "") -> str:
    prefix = f"{table_prefix}." if table_prefix else ""
    select_parts = []
    for column in ("transcript_id", "gene_names"):
        if table_has_column("gs_ptm", column):
            select_parts.append(f"{prefix}{column} AS {column}")
        else:
            select_parts.append(f"'' AS {column}")
    return ",\n            ".join(select_parts)


def build_identifier_match_condition(columns: list[str], quoted_query: str, normalized_quoted: str) -> str:
    clauses: list[str] = []
    for column in columns:
        clauses.append(f"LOWER(BTRIM({column})) = LOWER(BTRIM({quoted_query}))")
        clauses.append(
            f"""
            (
                {normalized_quoted} <> ''
                AND EXISTS (
                    SELECT 1
                    FROM regexp_split_to_table(LOWER(COALESCE({column}, '')), '[[:space:],;|/]+') AS tok
                    WHERE tok <> ''
                      AND REGEXP_REPLACE(tok, '[^a-z0-9]', '', 'g') = {normalized_quoted}
                )
            )
            """
        )
    return " OR ".join(f"({clause})" for clause in clauses)


def build_single_identifier_match_condition(column: str, quoted_query: str, normalized_quoted: str) -> str:
    return build_identifier_match_condition([column], quoted_query, normalized_quoted)


def build_identifier_fuzzy_condition(columns: list[str], normalized_quoted: str) -> str:
    return " OR ".join(
        (
            f"REGEXP_REPLACE(LOWER(COALESCE({column}, '')), '[^a-z0-9]', '', 'g') "
            f"LIKE '%' || {normalized_quoted} || '%'"
        )
        for column in columns
    )


def build_single_identifier_fuzzy_condition(column: str, normalized_quoted: str) -> str:
    return build_identifier_fuzzy_condition([column], normalized_quoted)


def collect_identifier_tokens(*values: Any) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()

    for value in values:
        text = str(value or "").strip()
        if not text:
            continue
        candidates = [text]
        candidates.extend(split_gene_aliases(text))
        for matched in re.findall(r"\bGN=([^\s;|,/]+)", text):
            candidates.append(matched)

        for candidate in candidates:
            clean = candidate.strip()
            if not clean:
                continue
            lowered = clean.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            output.append(clean)

    return output


def fetch_protein_sequence_by_identifiers(identifiers: list[str]) -> str:
    tokens = collect_identifier_tokens(*identifiers)
    if not tokens:
        return ""

    for token in tokens:
        exact_value = pg_quote(token.lower())
        normalized_token = normalize_identifier_token(token)
        normalized_value = pg_quote(normalized_token) if normalized_token else "''"

        rows = run_psql_csv_query(
            f"""
            SELECT protein
            FROM ptm.protein_sequence
            WHERE LOWER(BTRIM(gene_name)) = {exact_value}
               OR (
                    {normalized_value} <> ''
                    AND REGEXP_REPLACE(LOWER(COALESCE(gene_name, '')), '[^a-z0-9]', '', 'g') = {normalized_value}
               )
            ORDER BY created_at DESC
            LIMIT 1;
            """
        )
        if rows:
            return "".join(str(rows[0].get("protein", "")).split()).upper()

    return ""


def fetch_protein_sequence_by_gene_name(gene_name: str) -> str:
    if not gene_name:
        return ""

    return fetch_protein_sequence_by_identifiers([gene_name])


def fetch_gene_name_by_exact_sequence(sequence: str) -> str:
    if not sequence:
        return ""

    rows = run_psql_csv_query(
        f"""
        SELECT gene_name
        FROM ptm.protein_sequence
        WHERE protein = {pg_quote(sequence)}
        ORDER BY created_at DESC
        LIMIT 1;
        """
    )
    if not rows:
        return ""
    return str(rows[0].get("gene_name", "")).strip()


def fetch_blast_candidate_sequences(species: str = DEFAULT_SPECIES, max_candidates: int = BLAST_MAX_DB_SEQUENCES) -> list[dict[str, str]]:
    species_condition = build_species_sql_condition(species, "gs")
    modification_condition = build_modification_sql_condition("gs.ptm_types")
    option = get_species_option(species)
    source_terms = [
        normalize_species_key(species),
        *[str(term) for term in option.get("terms", [])],
    ]
    if normalize_species_key(species) == "glycine_max":
        source_terms.extend(["glycine", "soybean"])
    elif normalize_species_key(species) == "bradyrhizobium_diazoefficiens":
        source_terms.extend(["bradyrhizobium", "diazoefficiens", "rhizobium"])
    source_terms = sorted({term.strip().lower().replace(" ", "_") for term in source_terms if term.strip()})
    source_clauses = []
    for term in source_terms:
        source_clauses.append(f"LOWER(COALESCE(ib.source_name, '')) LIKE '%{term}%'")
        source_clauses.append(f"LOWER(COALESCE(ib.notes, '')) LIKE '%{term}%'")
    source_condition = " OR ".join(source_clauses) if source_clauses else "FALSE"
    transcript_summary_select = (
        "MIN(NULLIF(BTRIM(transcript_id), '')) AS transcript_id,"
        if table_has_column("gs_ptm", "transcript_id")
        else "'' AS transcript_id,"
    )
    gene_names_summary_select = (
        "MIN(NULLIF(BTRIM(gene_names), '')) AS gene_names,"
        if table_has_column("gs_ptm", "gene_names")
        else "'' AS gene_names,"
    )
    return run_psql_csv_query(
        f"""
        WITH gs_summary AS (
            SELECT
                BTRIM(gene_name) AS gene_name,
                MIN(NULLIF(BTRIM(protein_accession), '')) AS protein_accession,
                MIN(NULLIF(BTRIM(organism), '')) AS organism,
                MIN(NULLIF(BTRIM(protein_description), '')) AS protein_description,
                {transcript_summary_select}
                {gene_names_summary_select}
                COUNT(*) FILTER (WHERE position > 0 AND NULLIF(BTRIM(ptm_types), '') IS NOT NULL) AS total_sites,
                COUNT(DISTINCT NULLIF(BTRIM(ptm_types), '')) FILTER (WHERE position > 0) AS modification_type_count,
                STRING_AGG(DISTINCT NULLIF(BTRIM(ptm_types), ''), ', ' ORDER BY NULLIF(BTRIM(ptm_types), '')) AS ptm_types
            FROM ptm.gs_ptm gs
            WHERE {species_condition}
              AND {modification_condition}
              AND NULLIF(BTRIM(gene_name), '') IS NOT NULL
            GROUP BY BTRIM(gene_name)
        ),
        selected_batches AS (
            SELECT DISTINCT ib.batch_id
            FROM ptm.import_batch ib
            WHERE ib.source_type = 'protein_sequence'
              AND ({source_condition})
        ),
        selected_batch_state AS (
            SELECT COUNT(*) AS selected_count
            FROM selected_batches
        )
        SELECT
            ps.gene_name,
            ps.protein,
            COALESCE(gs_summary.protein_accession, '') AS protein_accession,
            COALESCE(gs_summary.organism, {pg_quote(str(option.get("display", species)))}) AS organism,
            COALESCE(gs_summary.protein_description, '') AS protein_description,
            COALESCE(gs_summary.transcript_id, '') AS transcript_id,
            COALESCE(gs_summary.gene_names, '') AS gene_names,
            COALESCE(gs_summary.total_sites, 0) AS total_sites,
            COALESCE(gs_summary.modification_type_count, 0) AS modification_type_count,
            COALESCE(gs_summary.ptm_types, '') AS ptm_types
        FROM ptm.protein_sequence ps
        LEFT JOIN gs_summary
          ON LOWER(BTRIM(ps.gene_name)) = LOWER(BTRIM(gs_summary.gene_name))
        LEFT JOIN ptm.import_batch ib
          ON ps.source_batch_id = ib.batch_id
        CROSS JOIN selected_batch_state sbs
        WHERE NULLIF(BTRIM(ps.protein), '') IS NOT NULL
          AND (
            sbs.selected_count = 0
            OR ps.source_batch_id IN (SELECT batch_id FROM selected_batches)
          )
        ORDER BY COALESCE(gs_summary.total_sites, 0) DESC, ps.gene_name
        LIMIT {int(max_candidates)};
        """
    )


def keep_primary_target_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    if not rows:
        return []

    first = rows[0]
    primary_gene = (first.get("gene_name") or "").strip()
    primary_accession = (first.get("protein_accession") or "").strip()
    primary_organism = (first.get("organism") or "").strip()

    kept: list[dict[str, str]] = []
    for row in rows:
        row_gene = (row.get("gene_name") or "").strip()
        row_accession = (row.get("protein_accession") or "").strip()
        row_organism = (row.get("organism") or "").strip()
        if (
            row_gene == primary_gene
            and row_accession == primary_accession
            and row_organism == primary_organism
        ):
            kept.append(row)
    return kept if kept else rows


def split_identifier_query(raw_value: str) -> list[str]:
    tokens = re.split(r"[,;\s]+", raw_value.strip())
    output: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        value = token.strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        output.append(value)
    return output


def _format_plaza_gene_id(transcript_id: str, gene_names: str = "", gene_name: str = "") -> str:
    candidates = collect_identifier_tokens(transcript_id, gene_names, gene_name)
    for candidate in candidates:
        matched = re.search(r"(glyma)[._](\d+g\d+)", candidate, flags=re.IGNORECASE)
        if matched:
            return f"Glyma.{matched.group(2).upper()}"
    return ""


def external_id_tokens(value: Any) -> list[str]:
    text = str(value or "").strip()
    if not text or text == "-":
        return []

    tokens: list[str] = []
    seen: set[str] = set()
    for token in re.split(r"[,;\s|]+", text):
        clean = token.strip()
        if not clean or clean == "-":
            continue
        lowered = clean.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        tokens.append(clean)
    return tokens


def phytozome_gene_url(identifier: Any) -> str:
    clean = str(identifier or "").strip()
    if not clean:
        return ""
    return "https://phytozome-next.jgi.doe.gov/report/gene/Gmax_Wm82_a4_v1/" + urllib.parse.quote(clean, safe="")


def uniprot_entry_url(identifier: Any) -> str:
    clean = str(identifier or "").strip()
    if not clean:
        return ""
    return "https://www.uniprot.org/uniprotkb/" + urllib.parse.quote(clean, safe="") + "/entry"


def _format_overview_id(query: str, gene_name: str, accession: str, transcript_id: str, gene_names: str) -> str:
    clean_query = query.strip()
    if clean_query:
        return re.sub(r"[.]p$", "", clean_query, flags=re.IGNORECASE)
    for candidate in collect_identifier_tokens(transcript_id, gene_name, accession, gene_names):
        if candidate:
            return re.sub(r"[.]p$", "", candidate, flags=re.IGNORECASE)
    return ""


def build_protein_overview_row(query: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    if not rows:
        return {
            "query": query,
            "display_id": query,
            "gene_name": "",
            "protein_accession": "",
            "uniprot_ids": "",
            "organism": "",
            "protein_description": "",
            "description": "",
            "transcript_id": "",
            "gene_names": "",
            "plaza_gene_id": "",
            "modification_type_count": 0,
            "total_sites": 0,
            "ptm_summary": "",
            "select_key": query,
            "status": "No result",
            "has_result": False,
        }

    first = rows[0]
    gene_name = str(first.get("gene_name", "")).strip()
    accession = str(first.get("protein_accession", "")).strip()
    organism = str(first.get("organism", "")).strip()
    description = str(first.get("protein_description", "")).strip()
    transcript_id = str(first.get("transcript_id", "")).strip()
    gene_names = str(first.get("gene_names", "")).strip()

    ptm_counts: dict[str, int] = {}
    valid_site_count = 0
    for row in rows:
        try:
            if int(row.get("position", "") or 0) <= 0:
                continue
        except (TypeError, ValueError):
            continue
        ptm_type = str(row.get("ptm_types", "")).strip()
        if not is_visual_ptm_code(ptm_type):
            continue
        valid_site_count += 1
        ptm_counts[ptm_type] = ptm_counts.get(ptm_type, 0) + 1

    ordered_ptm_types = order_ptm_codes(set(ptm_counts))
    ordered_ptm_types.extend(sorted(code for code in ptm_counts if code not in ordered_ptm_types))
    ptm_summary = "; ".join(f"{code}: {ptm_counts[code]}" for code in ordered_ptm_types)

    return {
        "query": query,
        "display_id": _format_overview_id(query, gene_name, accession, transcript_id, gene_names),
        "gene_name": gene_name,
        "protein_accession": accession,
        "uniprot_ids": accession,
        "organism": organism,
        "protein_description": description,
        "description": description,
        "transcript_id": transcript_id,
        "gene_names": gene_names,
        "plaza_gene_id": _format_plaza_gene_id(transcript_id, gene_names, gene_name),
        "modification_type_count": len(ptm_counts),
        "total_sites": valid_site_count,
        "ptm_summary": ptm_summary,
        "select_key": gene_name or accession or transcript_id or query,
        "status": "Matched" if valid_site_count else "Matched, no valid PTM site",
        "has_result": valid_site_count > 0,
    }


def build_identifier_match_rows(rows: list[dict[str, str]], query: str) -> list[dict[str, Any]]:
    query_tokens = {token.lower() for token in collect_identifier_tokens(query)}
    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}

    for row in rows:
        gene_name = str(row.get("gene_name", "")).strip()
        accession = str(row.get("protein_accession", "")).strip()
        organism = str(row.get("organism", "")).strip()
        description = str(row.get("protein_description", "")).strip()
        transcript_id = str(row.get("transcript_id", "")).strip()
        gene_names = str(row.get("gene_names", "")).strip()
        key = (gene_name, accession, organism)

        bucket = grouped.get(key)
        if bucket is None:
            row_tokens = {
                token.lower()
                for token in collect_identifier_tokens(gene_name, accession, transcript_id, gene_names)
            }
            is_exact = bool(query_tokens & row_tokens)
            select_key = gene_name if gene_name else accession
            bucket = {
                "gene_name": gene_name,
                "protein_accession": accession,
                "transcript_id": transcript_id,
                "gene_names": gene_names,
                "organism": organism,
                "protein_description": description,
                "site_count": 0,
                "is_exact": is_exact,
                "select_key": select_key,
            }
            grouped[key] = bucket

        try:
            if int(row.get("position", "")) > 0:
                bucket["site_count"] += 1
        except (TypeError, ValueError):
            pass

    output = list(grouped.values())
    output.sort(
        key=lambda item: (
            0 if item.get("is_exact") else 1,
            -(int(item.get("site_count", 0))),
            str(item.get("gene_name", "")),
            str(item.get("protein_accession", "")),
        )
    )
    return output


def fetch_sites_from_identifier_lookup(gene_query: str, species: str = DEFAULT_SPECIES) -> list[dict[str, str]]:
    normalized_query = normalize_identifier_token(gene_query)
    if not normalized_query or not table_exists("identifier_lookup"):
        return []

    normalized_quoted = pg_quote(normalized_query)
    lookup_species_condition = build_species_sql_condition(species, "il")
    modification_condition = build_modification_sql_condition("gs.ptm_types")
    optional_identifier_select = build_gs_optional_identifier_select("gs")

    return run_psql_csv_query(
        f"""
        WITH lookup_matches AS (
            SELECT
                il.organism,
                il.gene_name,
                il.protein_accession,
                il.identifier_priority
            FROM ptm.identifier_lookup il
            WHERE il.identifier_norm = {normalized_quoted}
              AND {lookup_species_condition}
        ),
        best_priority AS (
            SELECT MIN(identifier_priority) AS identifier_priority
            FROM lookup_matches
        ),
        targets AS (
            SELECT DISTINCT
                lm.organism,
                lm.gene_name,
                lm.protein_accession,
                lm.identifier_priority
            FROM lookup_matches lm
            INNER JOIN best_priority bp
              ON lm.identifier_priority = bp.identifier_priority
        )
        SELECT
            gs.organism,
            gs.ptm_types,
            gs.protein_accession,
            gs.position,
            gs.amino_acid,
            gs.protein_description,
            gs.gene_name,
            {optional_identifier_select},
            gs.subcellular_localization,
            gs.w4m_1,
            gs.w4m_2,
            gs.w4m_3,
            gs.w12m_1,
            gs.w12m_2,
            gs.w12m_3,
            gs.w12m_w4m_ratio,
            gs.w12m_w4m_p_value,
            gs.w12m_w4m_type
        FROM ptm.gs_ptm gs
        INNER JOIN targets t
          ON gs.organism = t.organism
         AND gs.gene_name = t.gene_name
         AND gs.protein_accession = t.protein_accession
        WHERE {modification_condition}
        ORDER BY t.identifier_priority, gs.position ASC;
        """
    )


def fetch_sites_for_identifier(gene_query: str, species: str = DEFAULT_SPECIES) -> list[dict[str, str]]:
    lookup_rows = fetch_sites_from_identifier_lookup(gene_query, species)
    if lookup_rows:
        return lookup_rows

    quoted_query = pg_quote(gene_query)
    normalized_exact_query = normalize_identifier_token(gene_query)
    normalized_exact_quoted = pg_quote(normalized_exact_query) if normalized_exact_query else "''"
    species_condition = build_species_sql_condition(species)
    modification_condition = build_modification_sql_condition("ptm_types")
    identifier_columns = get_gs_identifier_columns()
    optional_identifier_select = build_gs_optional_identifier_select()

    def build_priority_case(conditions_by_column: dict[str, str]) -> str:
        clauses = [
            f"WHEN ({conditions_by_column[column]}) THEN {idx}"
            for idx, column in enumerate(identifier_columns)
            if column in conditions_by_column
        ]
        return "CASE " + " ".join(clauses) + " ELSE 99 END"

    def run_identifier_query(condition: str, priority_case: str) -> list[dict[str, str]]:
        return run_psql_csv_query(
            f"""
            SELECT
                organism,
                ptm_types,
                protein_accession,
                position,
                amino_acid,
                protein_description,
                gene_name,
                {optional_identifier_select},
                subcellular_localization,
                w4m_1,
                w4m_2,
                w4m_3,
                w12m_1,
                w12m_2,
                w12m_3,
                w12m_w4m_ratio,
                w12m_w4m_p_value,
                w12m_w4m_type
            FROM ptm.gs_ptm
            WHERE (
                {condition}
            )
              AND {species_condition}
              AND {modification_condition}
            ORDER BY {priority_case}, position ASC;
            """
        )

    exact_conditions_by_column = {
        column: build_single_identifier_match_condition(
            column,
            quoted_query,
            normalized_exact_quoted,
        )
        for column in identifier_columns
    }
    exact_condition = " OR ".join(f"({condition})" for condition in exact_conditions_by_column.values())
    exact_rows = run_identifier_query(exact_condition, build_priority_case(exact_conditions_by_column))
    if exact_rows:
        return exact_rows

    normalized_query = re.sub(r"[^a-z0-9]", "", gene_query.strip().lower())
    if not normalized_query:
        return []
    normalized_query = re.sub(r"^glyma", "", normalized_query)
    if len(normalized_query) < 4:
        return []

    normalized_quoted = pg_quote(normalized_query)
    fuzzy_conditions_by_column = {
        column: build_single_identifier_fuzzy_condition(column, normalized_quoted)
        for column in identifier_columns
    }
    fuzzy_condition = " OR ".join(f"({condition})" for condition in fuzzy_conditions_by_column.values())
    return run_identifier_query(fuzzy_condition, build_priority_case(fuzzy_conditions_by_column))


def fetch_sites_by_gene_name(gene_name: str, species: str = DEFAULT_SPECIES) -> list[dict[str, str]]:
    if not gene_name:
        return []
    normalized_exact_query = normalize_identifier_token(gene_name)
    normalized_exact_quoted = pg_quote(normalized_exact_query) if normalized_exact_query else "''"
    species_condition = build_species_sql_condition(species)
    modification_condition = build_modification_sql_condition("ptm_types")
    optional_identifier_select = build_gs_optional_identifier_select()

    return run_psql_csv_query(
        f"""
        SELECT
            organism,
            ptm_types,
            protein_accession,
            position,
            amino_acid,
            protein_description,
            gene_name,
            {optional_identifier_select},
            subcellular_localization,
            w4m_1,
            w4m_2,
            w4m_3,
            w12m_1,
            w12m_2,
            w12m_3,
            w12m_w4m_ratio,
            w12m_w4m_p_value,
            w12m_w4m_type
        FROM ptm.gs_ptm
        WHERE (
            LOWER(BTRIM(gene_name)) = LOWER(BTRIM({pg_quote(gene_name)}))
            OR (
                {normalized_exact_quoted} <> ''
                AND EXISTS (
                    SELECT 1
                    FROM regexp_split_to_table(LOWER(COALESCE(gene_name, '')), '[[:space:],;|/]+') AS tok
                    WHERE tok <> ''
                      AND REGEXP_REPLACE(tok, '[^a-z0-9]', '', 'g') = {normalized_exact_quoted}
                )
            )
        )
          AND {species_condition}
          AND {modification_condition}
        ORDER BY position ASC;
        """
    )


def _query_checkbox_checked(query_params: Any, key: str, default: bool) -> bool:
    if key in query_params:
        return True
    return default


def _clamp_int(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(maximum, value))


def _clamp_float(value: float, minimum: float, maximum: float) -> float:
    if not math.isfinite(value):
        return minimum
    return max(minimum, min(maximum, value))


def _build_ptm_alias_map() -> dict[str, str]:
    aliases: dict[str, str] = {}
    for code, style in PTM_STYLE.items():
        aliases[code.lower()] = code
        tag = str(style.get("tag", "")).strip().lower()
        if tag:
            aliases[tag] = code
    return aliases


PTM_ALIAS_MAP = _build_ptm_alias_map()


def _parse_ptm_condition(text: str) -> tuple[dict[str, Any] | None, str]:
    raw = text.strip()
    if not raw:
        return None, "PTM 条件不能为空。"

    lowered = raw.lower()
    if lowered == "xx":
        return {"mode": "wildcard", "codes": [], "raw": raw}, ""

    if "&" in raw and "|" in raw:
        return None, "同一个 PTM 条件里不能同时混用 '&' 和 '|'。"

    sep = "&" if "&" in raw else "|" if "|" in raw else ""
    parts = [raw] if not sep else raw.split(sep)
    codes: list[str] = []
    for part in parts:
        token = part.strip().lower()
        if not token:
            return None, "PTM 条件格式错误，请检查括号里的内容。"
        mapped = PTM_ALIAS_MAP.get(token)
        if not mapped:
            return None, f"未识别的 PTM 类型: {part.strip()}。可用示例: Ub, Ac, ST, Sc, Cr, Og。"
        if mapped not in codes:
            codes.append(mapped)

    mode = "and" if sep == "&" else "or"
    return {"mode": mode, "codes": codes, "raw": raw}, ""


def parse_ptm_search_expression(expression: str) -> tuple[dict[str, Any] | None, str]:
    compact = "".join(expression.split())
    if not compact:
        return None, "请输入 Search Expression。"

    tokens: list[dict[str, Any]] = []
    constraints: list[dict[str, Any]] = []
    idx = 0
    while idx < len(compact):
        current = compact[idx]
        aa_display = ""
        aa_regex = ""

        if current == "[":
            end_idx = compact.find("]", idx + 1)
            if end_idx == -1:
                return None, "字符集合缺少右括号 ']'。"
            inner = compact[idx + 1:end_idx].upper()
            if not inner:
                return None, "字符集合 [] 不能为空。"
            if any(not ch.isalpha() for ch in inner):
                return None, "字符集合 [] 内仅支持氨基酸字母。"
            aa_display = f"[{inner}]"
            aa_regex = aa_display
            idx = end_idx + 1
        elif current in {"X", "x", "."}:
            aa_display = "X"
            aa_regex = "[A-Z]"
            idx += 1
        elif current.isalpha():
            aa_display = current.upper()
            aa_regex = aa_display
            idx += 1
        elif current in {"?", "+", "*", "{", "}", "|", "^", "$"}:
            return None, "当前版本暂不支持 ?, +, *, {}, |, ^, $ 等正则操作符。"
        else:
            return None, f"不支持的字符: {current}"

        token_offset = len(tokens)
        if idx < len(compact) and compact[idx] == "(":
            close_idx = compact.find(")", idx + 1)
            if close_idx == -1:
                return None, "PTM 条件缺少右括号 ')'。"
            parsed_ptm, error = _parse_ptm_condition(compact[idx + 1:close_idx])
            if error:
                return None, error
            constraints.append(
                {
                    "offset": token_offset,
                    "aa_display": aa_display,
                    "mode": parsed_ptm["mode"],
                    "codes": parsed_ptm["codes"],
                    "raw": parsed_ptm["raw"],
                }
            )
            idx = close_idx + 1

        tokens.append({"display": aa_display, "regex": aa_regex})

    if not tokens:
        return None, "Search Expression 不能为空。"
    if not constraints:
        return None, "每个表达式至少包含一个 PTM 条件，例如 M(Ub)。"

    motif_regex = "".join(token["regex"] for token in tokens)
    required_codes = sorted({code for rule in constraints for code in rule.get("codes", [])})
    return {
        "expression": compact,
        "tokens": tokens,
        "constraints": constraints,
        "motif_regex": motif_regex,
        "motif_length": len(tokens),
        "required_codes": required_codes,
    }, ""


def fetch_ptm_rows_with_sequence(required_codes: list[str], species: str = DEFAULT_SPECIES) -> list[dict[str, str]]:
    type_filter = ""
    if required_codes:
        quoted = ", ".join(pg_quote(code) for code in required_codes)
        type_filter = f"AND BTRIM(ptm.gs_ptm.ptm_types) IN ({quoted})"
    species_condition = build_species_sql_condition(species, "ptm.gs_ptm")
    modification_condition = build_modification_sql_condition("ptm.gs_ptm.ptm_types")

    return run_psql_csv_query(
        f"""
        SELECT
            ptm.gs_ptm.organism,
            ptm.gs_ptm.ptm_types,
            ptm.gs_ptm.protein_accession,
            ptm.gs_ptm.position,
            ptm.gs_ptm.amino_acid,
            ptm.gs_ptm.protein_description,
            ptm.gs_ptm.gene_name,
            ptm.gs_ptm.subcellular_localization,
            ptm.protein_sequence.protein AS protein_sequence
        FROM ptm.gs_ptm
        LEFT JOIN ptm.protein_sequence
          ON LOWER(BTRIM(ptm.gs_ptm.gene_name)) = LOWER(BTRIM(ptm.protein_sequence.gene_name))
        WHERE {species_condition}
          AND {modification_condition}
          AND NULLIF(BTRIM(ptm.gs_ptm.gene_name), '') IS NOT NULL
          {type_filter}
        ORDER BY ptm.gs_ptm.gene_name, ptm.gs_ptm.protein_accession, ptm.gs_ptm.position ASC;
        """
    )


def _gene_representative_key(gene_name: str) -> str:
    clean = gene_name.strip()
    matched = re.match(r"^(.*)\.\d+$", clean)
    if matched:
        return matched.group(1)
    return clean


def _format_ptm_hit_label(mode: str, matched_codes: list[str]) -> str:
    if not matched_codes:
        return "PTM"
    if mode == "and":
        return "&".join(matched_codes)
    return "|".join(matched_codes)


PTM_EXAMPLE_RESIDUE_BY_CODE = {
    "Ub": "K",
    "Ac": "K",
    "ST": "[STY]",
    "Sc": "K",
    "Cr": "K",
    "3o": "K",
    "LLa": "K",
    "DLa": "K",
    "lg": "N",
    "IOg": "[ST]",
    "Og": "[ST]",
    "Sn": "C",
    "Sl": "C",
    "Sg": "C",
    "Ss": "C",
}


def _example_residue_for_ptm(code: str, label: str) -> str:
    preset = PTM_EXAMPLE_RESIDUE_BY_CODE.get(code)
    if preset:
        return preset

    matched = re.search(r"\(([A-Za-z/]+)\)\s*$", label.strip())
    if not matched:
        return "X"

    token = matched.group(1).upper()
    letters = [ch for ch in token if "A" <= ch <= "Z"]
    if not letters:
        return "X"

    dedup: list[str] = []
    seen: set[str] = set()
    for ch in letters:
        if ch in seen:
            continue
        seen.add(ch)
        dedup.append(ch)

    if len(dedup) == 1:
        return dedup[0]
    return "[" + "".join(dedup) + "]"


def _build_ptm_reference_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for code in PTM_PRIORITY:
        style = get_ptm_style(code)
        label = style.get("label", code)
        tag = str(style.get("tag", "")).strip().lower() or code.lower()
        residue = _example_residue_for_ptm(code, str(label))
        rows.append(
            {
                "code": code,
                "tag": style.get("tag", ""),
                "label": label,
                "example": f"{residue}({tag})",
            }
        )
    return rows


def run_ptm_expression_search(
    parsed: dict[str, Any],
    *,
    sequence_length: int,
    representative_only: bool,
    peptides_unique: bool,
    max_results: int,
    species: str = DEFAULT_SPECIES,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows = fetch_ptm_rows_with_sequence(parsed.get("required_codes", []), species)
    if not rows:
        return [], {"matched_proteins": 0, "matched_sites": 0, "truncated": 0}

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        gene_name = str(row.get("gene_name", "")).strip()
        if not gene_name:
            continue
        accession = str(row.get("protein_accession", "")).strip()
        key = (gene_name, accession)
        bucket = grouped.get(key)
        if bucket is None:
            raw_sequence = "".join(str(row.get("protein_sequence", "")).split()).upper()
            bucket = {
                "gene_name": gene_name,
                "protein_accession": accession,
                "organism": str(row.get("organism", "")).strip(),
                "protein_description": str(row.get("protein_description", "")).strip(),
                "subcellular_localization": str(row.get("subcellular_localization", "")).strip(),
                "sequence": raw_sequence,
                "ptm_map": {},
            }
            grouped[key] = bucket

        position_text = str(row.get("position", "")).strip()
        ptm_code = str(row.get("ptm_types", "")).strip()
        if not position_text or not ptm_code:
            continue
        try:
            position = int(position_text)
        except ValueError:
            continue
        bucket["ptm_map"].setdefault(position, set()).add(ptm_code)

    if not grouped:
        return [], {"matched_proteins": 0, "matched_sites": 0, "truncated": 0}

    motif_regex = str(parsed["motif_regex"])
    compiled = re.compile(f"(?=({motif_regex}))")
    motif_len = int(parsed["motif_length"])
    constraints = parsed["constraints"]

    matches: list[dict[str, Any]] = []
    for bucket in grouped.values():
        sequence = str(bucket.get("sequence", ""))
        if not sequence:
            continue

        for match in compiled.finditer(sequence):
            start_idx = match.start()
            motif_start = start_idx + 1
            motif_end = motif_start + motif_len - 1
            matched_sites: list[dict[str, Any]] = []
            passed = True

            for rule in constraints:
                site_pos = motif_start + int(rule["offset"])
                site_idx = site_pos - 1
                aa_here = sequence[site_idx]
                site_types = bucket["ptm_map"].get(site_pos, set())
                if not site_types:
                    passed = False
                    break

                if rule["mode"] == "wildcard":
                    matched_codes = order_ptm_codes(site_types)
                elif rule["mode"] == "and":
                    needed = set(rule.get("codes", []))
                    if not needed.issubset(site_types):
                        passed = False
                        break
                    matched_codes = [code for code in rule["codes"] if code in site_types]
                else:
                    matched_codes = [code for code in order_ptm_codes(site_types) if code in set(rule.get("codes", []))]
                    if not matched_codes:
                        passed = False
                        break

                matched_sites.append(
                    {
                        "position": site_pos,
                        "amino_acid": aa_here,
                        "matched_codes": matched_codes,
                        "mode": rule["mode"],
                        "left_context": sequence[max(0, site_idx - sequence_length):site_idx],
                        "right_context": sequence[site_idx + 1:min(len(sequence), site_idx + 1 + sequence_length)],
                    }
                )

            if not passed:
                continue

            left_start = max(0, start_idx - sequence_length)
            right_end = min(len(sequence), start_idx + motif_len + sequence_length)
            left_context = sequence[left_start:start_idx]
            motif_context = sequence[start_idx:start_idx + motif_len]
            right_context = sequence[start_idx + motif_len:right_end]

            site_labels = [
                f"{site['position']}:{site['amino_acid']}({ _format_ptm_hit_label(site['mode'], site['matched_codes']) })"
                for site in matched_sites
            ]
            matches.append(
                {
                    "gene_name": bucket["gene_name"],
                    "protein_accession": bucket["protein_accession"],
                    "organism": bucket["organism"],
                    "protein_description": bucket["protein_description"],
                    "subcellular_localization": bucket["subcellular_localization"],
                    "motif_start": motif_start,
                    "motif_end": motif_end,
                    "motif_sequence": motif_context,
                    "site_hits_text": "; ".join(site_labels),
                    "matched_site_count": len(matched_sites),
                    "matched_sites": matched_sites,
                    "left_context": left_context,
                    "motif_context": motif_context,
                    "right_context": right_context,
                }
            )

    if representative_only:
        kept: list[dict[str, Any]] = []
        seen_keys: set[str] = set()
        for row in sorted(matches, key=lambda item: (item["gene_name"], item["protein_accession"], item["motif_start"])):
            key = _gene_representative_key(str(row["gene_name"]))
            if key in seen_keys:
                continue
            seen_keys.add(key)
            kept.append(row)
        matches = kept

    if peptides_unique:
        motif_gene_map: dict[str, set[str]] = {}
        for row in matches:
            motif = str(row.get("motif_sequence", ""))
            motif_gene_map.setdefault(motif, set()).add(_gene_representative_key(str(row.get("gene_name", ""))))
        matches = [row for row in matches if len(motif_gene_map.get(str(row.get("motif_sequence", "")), set())) == 1]

    matches = sorted(matches, key=lambda item: (item["gene_name"], item["protein_accession"], item["motif_start"]))
    truncated = 1 if len(matches) > max_results else 0
    if truncated:
        matches = matches[:max_results]

    protein_keys = {(row["gene_name"], row["protein_accession"]) for row in matches}
    total_sites = sum(int(row.get("matched_site_count", 0)) for row in matches)
    return matches, {"matched_proteins": len(protein_keys), "matched_sites": total_sites, "truncated": truncated}


def _species_table_label(organism: str) -> str:
    normalized = organism.strip().lower()
    if "glycine max" in normalized or "soybean" in normalized:
        return "gmx"
    if "bradyrhizobium" in normalized or "diazoefficiens" in normalized:
        return "bdi"
    return organism.strip() or "-"


def build_ptm_site_rows(matches: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, int, int, str]] = set()

    for match in matches:
        gene_name = str(match.get("gene_name", "")).strip()
        accession = str(match.get("protein_accession", "")).strip()
        description = str(match.get("protein_description", "")).strip()
        organism = str(match.get("organism", "")).strip()
        motif_start = int(match.get("motif_start", 0) or 0)
        motif_end = int(match.get("motif_end", 0) or 0)

        for site in match.get("matched_sites", []):
            pos = int(site.get("position", 0) or 0)
            aa = str(site.get("amino_acid", "")).strip()
            left_ctx = str(site.get("left_context", ""))
            right_ctx = str(site.get("right_context", ""))
            hit_codes = [str(code) for code in site.get("matched_codes", []) if str(code).strip()]
            hit_label = _format_ptm_hit_label(str(site.get("mode", "")), hit_codes)

            dedupe_key = (gene_name, accession, pos, motif_start, "|".join(hit_codes))
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)

            rows.append(
                {
                    "gene_name": gene_name,
                    "protein_accession": accession,
                    "protein_description": description,
                    "organism": organism,
                    "species_label": _species_table_label(organism),
                    "ptm_position": pos,
                    "hit_aa": aa,
                    "hit_label": hit_label,
                    "left_context": left_ctx,
                    "right_context": right_ctx,
                    "motif_start": motif_start,
                    "motif_end": motif_end,
                }
            )

    rows.sort(key=lambda item: (item["gene_name"], item["protein_accession"], item["ptm_position"], item["motif_start"]))
    return rows


def paginate_rows(rows: list[dict[str, Any]], page: int, page_size: int) -> tuple[list[dict[str, Any]], dict[str, int]]:
    total = len(rows)
    total_pages = max(1, math.ceil(total / page_size)) if total > 0 else 1
    current = _clamp_int(page, 1, total_pages)
    start = (current - 1) * page_size
    end = start + page_size
    sliced = rows[start:end]

    return sliced, {
        "total_rows": total,
        "total_pages": total_pages,
        "current_page": current,
        "page_size": page_size,
        "start_row": 0 if total == 0 else start + 1,
        "end_row": min(end, total),
        "prev_page": current - 1 if current > 1 else 1,
        "next_page": current + 1 if current < total_pages else total_pages,
    }


def group_ptm_rows_by_protein(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    lookup: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    for row in rows:
        key = (
            str(row.get("gene_name", "")),
            str(row.get("protein_accession", "")),
            str(row.get("protein_description", "")),
            str(row.get("species_label", "")),
        )
        group = lookup.get(key)
        if group is None:
            group = {
                "gene_name": key[0],
                "protein_accession": key[1],
                "protein_description": key[2],
                "species_label": key[3],
                "site_rows": [],
                "rowspan": 0,
            }
            lookup[key] = group
            groups.append(group)

        group["site_rows"].append(
            {
                "ptm_position": row.get("ptm_position", ""),
                "left_context": row.get("left_context", ""),
                "hit_aa": row.get("hit_aa", ""),
                "right_context": row.get("right_context", ""),
                "hit_label": row.get("hit_label", ""),
            }
        )

    for group in groups:
        group["rowspan"] = len(group["site_rows"])

    return groups


def _uniq_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        text = item.strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _nested_value(node: Any, path: list[str], default: str = "") -> str:
    current = node
    for key in path:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
    if current is None:
        return default
    return str(current).strip()


def _extract_comment_texts(comment: dict[str, Any]) -> list[str]:
    texts: list[str] = []
    for text_item in comment.get("texts", []) or []:
        value = _nested_value(text_item, ["value"])
        if value:
            texts.append(value)
    return texts


def _normalize_accession(accession: str) -> str:
    if not accession:
        return ""
    token = accession.strip().split(";")[0].split(",")[0].strip()
    return token


def _build_uniprot_ssl_context() -> tuple[ssl.SSLContext, str]:
    if not UNIPROT_SSL_VERIFY:
        return ssl._create_unverified_context(), "verify=off"

    if UNIPROT_CA_FILE:
        return ssl.create_default_context(cafile=UNIPROT_CA_FILE), f"cafile={UNIPROT_CA_FILE}"

    if certifi is not None:
        try:
            ca_path = certifi.where()
            if ca_path:
                return ssl.create_default_context(cafile=ca_path), f"certifi={ca_path}"
        except Exception:
            pass

    return ssl.create_default_context(), "system-default"


@lru_cache(maxsize=256)
def fetch_uniprot_entry(accession: str) -> tuple[dict[str, Any] | None, str]:
    normalized = _normalize_accession(accession)
    if not normalized:
        return None, "Empty accession"

    url = f"https://rest.uniprot.org/uniprotkb/{urllib.parse.quote(normalized)}.json"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "SoybeanPTMViewer/1.0",
        },
    )
    ssl_context, ssl_source = _build_uniprot_ssl_context()
    try:
        with urllib.request.urlopen(request, timeout=UNIPROT_TIMEOUT_SEC, context=ssl_context) as response:
            payload = response.read().decode("utf-8")
        parsed = json.loads(payload)
        if isinstance(parsed, dict):
            return parsed, ""
        return None, "Invalid JSON payload"
    except urllib.error.HTTPError as exc:
        return None, f"HTTP {exc.code} [{ssl_source}]"
    except urllib.error.URLError as exc:
        return None, f"Network error [{ssl_source}]: {exc.reason}"
    except TimeoutError:
        return None, f"Request timeout [{ssl_source}]"
    except json.JSONDecodeError:
        return None, f"Invalid JSON response [{ssl_source}]"
    except Exception as exc:
        return None, f"{type(exc).__name__} [{ssl_source}]: {exc}"


def build_uniprot_context(accession: str, result_rows: list[dict[str, Any]], result_meta: dict[str, Any]) -> dict[str, Any]:
    normalized = _normalize_accession(accession)
    entry, error_reason = fetch_uniprot_entry(normalized)
    if not entry:
        fallback_entry_url = f"https://www.uniprot.org/uniprotkb/{normalized}/entry" if normalized else ""
        fallback_af_url = f"https://alphafold.ebi.ac.uk/entry/{normalized}" if normalized else ""
        reason = f" ({error_reason})" if error_reason else ""
        return {
            "available": False,
            "query_accession": normalized,
            "primary_accession": normalized,
            "entry_url": fallback_entry_url,
            "alphafold_id": normalized,
            "alphafold_url": fallback_af_url,
            "protein_name": str(result_meta.get("protein_description", "")).strip(),
            "db_subcellular_localization": str(result_meta.get("subcellular_localization", "")).strip(),
            "message": f"UniProt data is currently unavailable for this accession{reason}.",
        }

    primary_accession = _nested_value(entry, ["primaryAccession"]) or normalized
    entry_url = f"https://www.uniprot.org/uniprotkb/{primary_accession}/entry"

    protein_name = _nested_value(entry, ["proteinDescription", "recommendedName", "fullName", "value"])
    if not protein_name:
        submission_names = (entry.get("proteinDescription", {}) or {}).get("submissionNames", []) or []
        if submission_names:
            protein_name = _nested_value(submission_names[0], ["fullName", "value"])
    if not protein_name:
        protein_name = str(result_meta.get("protein_description", "")).strip()

    gene_names: list[str] = []
    for gene in entry.get("genes", []) or []:
        main_name = _nested_value(gene, ["geneName", "value"])
        if main_name:
            gene_names.append(main_name)
        for syn in gene.get("synonyms", []) or []:
            syn_name = _nested_value(syn, ["value"])
            if syn_name:
                gene_names.append(syn_name)
    gene_names = _uniq_preserve(gene_names)

    organism_name = _nested_value(entry, ["organism", "scientificName"]) or str(result_meta.get("organism", "")).strip()

    function_texts: list[str] = []
    catalytic_activities: list[str] = []
    subcellular_locations: list[str] = []

    for comment in entry.get("comments", []) or []:
        comment_type = str(comment.get("commentType", "")).strip().upper()
        if comment_type == "FUNCTION":
            function_texts.extend(_extract_comment_texts(comment))
        elif comment_type == "CATALYTIC ACTIVITY":
            reaction_name = _nested_value(comment, ["reaction", "name"])
            ec_number = _nested_value(comment, ["reaction", "ecNumber"])
            assembled = reaction_name
            if ec_number:
                assembled = f"{assembled} (EC {ec_number})" if assembled else f"EC {ec_number}"
            if assembled:
                catalytic_activities.append(assembled)
        elif comment_type == "SUBCELLULAR LOCATION":
            for loc in comment.get("subcellularLocations", []) or []:
                location = _nested_value(loc, ["location", "value"])
                topology = _nested_value(loc, ["topology", "value"])
                orientation = _nested_value(loc, ["orientation", "value"])
                bits = [location, topology, orientation]
                merged = " | ".join([b for b in bits if b])
                if merged:
                    subcellular_locations.append(merged)
            subcellular_locations.extend(_extract_comment_texts(comment))

    function_texts = _uniq_preserve(function_texts)
    catalytic_activities = _uniq_preserve(catalytic_activities)
    subcellular_locations = _uniq_preserve(subcellular_locations)

    go_terms: list[dict[str, str]] = []
    pdb_entries: list[dict[str, str]] = []
    alphafold_id = ""

    for ref in entry.get("uniProtKBCrossReferences", []) or []:
        db_name = str(ref.get("database", "")).strip()
        db_id = str(ref.get("id", "")).strip()
        props = {str(p.get("key", "")).strip(): str(p.get("value", "")).strip() for p in ref.get("properties", []) or []}

        if db_name == "GO" and db_id:
            go_terms.append(
                {
                    "id": db_id,
                    "term": props.get("GoTerm", ""),
                    "evidence": props.get("GoEvidenceType", ""),
                }
            )
        elif db_name == "PDB" and db_id:
            pdb_entries.append(
                {
                    "id": db_id,
                    "chains": props.get("Chains", ""),
                    "method": props.get("Method", ""),
                    "resolution": props.get("Resolution", ""),
                }
            )
        elif db_name == "AlphaFoldDB" and db_id:
            alphafold_id = db_id

    if not alphafold_id:
        alphafold_id = primary_accession

    feature_types = {"DOMAIN", "REGION", "ACT_SITE", "BINDING", "MOTIF", "SITE"}
    feature_items: list[dict[str, str]] = []
    for feat in entry.get("features", []) or []:
        feature_type = str(feat.get("type", "")).strip()
        if feature_type not in feature_types:
            continue
        begin = _nested_value(feat, ["location", "start", "value"])
        end = _nested_value(feat, ["location", "end", "value"])
        if begin and end and begin != end:
            pos_text = f"{begin}-{end}"
        else:
            pos_text = begin or end
        description = str(feat.get("description", "")).strip()
        feature_items.append({"type": feature_type, "position": pos_text, "description": description})
        if len(feature_items) >= 20:
            break

    ptm_sites = []
    for row in result_rows:
        ptm_sites.append(
            {
                "position": row.get("Position"),
                "amino_acid": row.get("Amino acid", ""),
                "ptm_type": row.get("PTM types", ""),
            }
        )

    return {
        "available": True,
        "query_accession": normalized,
        "primary_accession": primary_accession,
        "entry_url": entry_url,
        "protein_name": protein_name,
        "gene_names": gene_names[:12],
        "organism_name": organism_name,
        "function_texts": function_texts[:8],
        "catalytic_activities": catalytic_activities[:8],
        "subcellular_locations": subcellular_locations[:12],
        "go_terms": go_terms[:20],
        "alphafold_id": alphafold_id,
        "alphafold_url": f"https://alphafold.ebi.ac.uk/entry/{alphafold_id}" if alphafold_id else "",
        "pdb_entries": pdb_entries[:12],
        "feature_items": feature_items,
        "ptm_sites": ptm_sites[:100],
        "db_subcellular_localization": str(result_meta.get("subcellular_localization", "")).strip(),
        "message": "",
    }


def close_database_pool() -> None:
    if _DB_POOL is not None:
        _DB_POOL.closeall()


__all__ = [name for name in globals() if not name.startswith("__")]
