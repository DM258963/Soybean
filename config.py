import os
from pathlib import Path

# Resolve runtime paths from the repository root unless explicitly overridden.
BASE_DIR = Path(os.getenv("PTM_BASE_DIR", Path(__file__).resolve().parent)).resolve()

IMPORT_READY_DIR = BASE_DIR / "import_ready"

# BLAST indexes are generated locally and are not committed to the repository.
BLAST_DB_DIR = BASE_DIR / "blastdb_cache"

# Values point to BLAST database prefixes rather than individual index files.
BLAST_DB_PATHS = {
    "glycine_max": Path(os.getenv("PTM_BLAST_DB_GLYCINE_MAX", BASE_DIR / "data" / "blastdb" / "soybean")),
    "bradyrhizobium_diazoefficiens": Path(
        os.getenv("PTM_BLAST_DB_BRADYRHIZOBIUM_DIAZOEFFICIENS", BASE_DIR / "data" / "blastdb" / "rhizobium")
    ),
}

UNIPROT_CA_FILE = os.getenv("PTM_UNIPROT_CA_FILE", "").strip()

# Database defaults are suitable for local development; credentials stay in .env.
DB_CONFIG = {
    "service": os.getenv("PTM_DB_SERVICE", "postgres"),
    "dbname": os.getenv("PTM_DB_NAME", "ptm_prod"),
    "user": os.getenv("PTM_DB_USER", "myuser"),
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

# Limit the number of sequences used when rebuilding a local BLAST database.
BLAST_MAX_DB_SEQUENCES = int(os.getenv("PTM_BLAST_MAX_DB_SEQUENCES", "200000"))

# Public metadata for datasets expected under IMPORT_READY_DIR.
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


def env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


UNIPROT_TIMEOUT_SEC = float(os.getenv("PTM_UNIPROT_TIMEOUT_SEC", "10"))
UNIPROT_SSL_VERIFY = env_bool("PTM_UNIPROT_SSL_VERIFY", True)
