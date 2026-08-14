"""
Configuration for QuWARTS.

Paths, model settings, and extraction parameters. Override locations with
QUWARTS_PROJECT_ROOT, QUWARTS_SOURCE_DATA, QUWARTS_QUERY_DIR, QUWARTS_RESULTS_DIR,
or QUWARTS_DB_PATH.
"""

import os
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _default_project_root(repo_root: Path) -> Path:
    """Data, queries, and ground truth live in the repo by default."""
    env = os.getenv("QUWARTS_PROJECT_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    return repo_root


# ============================================================================
# Directory Paths
# ============================================================================

REPO_ROOT = _repo_root()
QUWARTS_DIR = REPO_ROOT
PROJECT_ROOT = _default_project_root(REPO_ROOT)
SOURCE_DATA_DIR = Path(os.getenv("QUWARTS_SOURCE_DATA", PROJECT_ROOT / "source_data"))
QUERY_DIR = Path(os.getenv("QUWARTS_QUERY_DIR", PROJECT_ROOT / "Query"))
RESULTS_DIR = Path(os.getenv("QUWARTS_RESULTS_DIR", PROJECT_ROOT / "results"))

CACHE_DIR = REPO_ROOT / ".cache"
DB_DIR = REPO_ROOT / ".databases"
SIEVE_DIR = REPO_ROOT / ".sieves"

# ============================================================================
# Database Configuration (SQLite)
# ============================================================================

# SQLite database path (relative to QuWARTS directory or absolute)
DB_PATH = os.getenv("QUWARTS_DB_PATH", str(DB_DIR / "quwarts.db"))

# Connection string for SQLAlchemy
DATABASE_URI = f"sqlite:///{DB_PATH}"

# ============================================================================
# Text Chunking Configuration
# ============================================================================

# Recursive character splitting parameters
CHUNK_SIZE = 2000  # characters (≈ 500 tokens at ~4 chars/token)
CHUNK_OVERLAP = 200  # characters (≈ 50 tokens)
CHUNK_SEPARATORS = ["\n\n", "\n", ". ", " ", ""]

# ============================================================================
# LLM Configuration (Ollama)
# ============================================================================

# Ollama settings
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b-instruct")
OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "300"))  # seconds
OLLAMA_MAX_RETRIES = 3
OLLAMA_RETRY_DELAY = 2  # seconds

# LLM extraction parameters
EXTRACTION_BATCH_SIZE = 10  # kept for schema stabilization sampling
EXTRACTION_TEMPERATURE = 0.1  # low temperature for consistency
EXTRACTION_MAX_TOKENS = 4096
COLUMN_BATCH_SIZE = 10  # max columns per LLM call; qwen2.5:7b handles 10 reliably
# For smaller local models, single-document calls are far more stable.
CHUNK_BATCH_SIZE = int(os.getenv("CHUNK_BATCH_SIZE", "1"))
TOP_K_CHUNKS_PER_ENTITY = 5  # max chunks fed to LLM per entity in entity-first extraction

# ============================================================================
# Entity Resolution Configuration
# ============================================================================

# Embedding models
BI_ENCODER_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Resolution thresholds
BI_ENCODER_THRESHOLD = 0.75  # for blocking
CROSS_ENCODER_THRESHOLD = 0.95  # for matching
TOP_K_CANDIDATES = 20  # number of candidates to retrieve

# ============================================================================
# Sieve Synthesis Configuration
# ============================================================================

# Sieve synthesis parameters
SIEVE_SAMPLE_SIZE = 5  # chunks to sample for synthesis
SIEVE_REFINEMENT_ITERATIONS = 3  # max refinement iterations
SIEVE_TEST_SIZE = 5  # chunks to test refined sieve

# ============================================================================
# Schema Stabilization Configuration
# ============================================================================

# Schema discovery parameters
SCHEMA_SAMPLE_SIZE = 50  # chunks for schema discovery
SCHEMA_KEY_FREQUENCY_THRESHOLD = 0.20  # 20% frequency to freeze key

# ============================================================================
# Workload Lattice Configuration
# ============================================================================

# Semantic types for column classification
SEMANTIC_TYPES = [
    "PERSON",
    "ORG",
    "DATE",
    "GPE",           # Geo-Political Entity
    "CODE",
    "MONEY",
    "QUANTITY",
    "QUANTITY_COUNT", # Cumulative count of discrete events (e.g. number of awards won)
    "PRODUCT",
    "EVENT",
    "OTHER"
]

# ============================================================================
# Metadata Registry Configuration
# ============================================================================

# Status values for metadata registry
STATUS_PARTIAL = "PARTIAL"
STATUS_FULL = "FULL"

# ============================================================================
# Logging Configuration
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_FILE = QUWARTS_DIR / "quwarts.log"

# ============================================================================
# Performance Configuration
# ============================================================================

# Parallel processing
MAX_WORKERS = int(os.getenv("MAX_WORKERS", "8"))
# Conservative default to avoid local Ollama saturation and retry storms.
MAX_PARALLEL_REQUESTS = int(os.getenv("MAX_PARALLEL_REQUESTS", "8"))
EXTRACTION_MAX_WORKERS = MAX_PARALLEL_REQUESTS  # alias used by entity-first extraction
NER_BATCH_SIZE = int(os.getenv("NER_BATCH_SIZE", "512"))  # spaCy pipe batch for NER grouping pass
# For strict prune-before-extract behavior, default to 0 so unassigned chunks
# (typically rejected by table relevance/identity gate) do not trigger costly
# brute-force extraction. Can be raised via env var if recall recovery is needed.
UNASSIGNED_CHUNK_CAP = int(os.getenv("UNASSIGNED_CHUNK_CAP", "0"))

# Fast path: extract query/workload-inferred columns directly from source docs
# (one doc ~= one extraction unit) instead of sweeping candidate chunks.
USE_PROJECTION_FASTPATH = os.getenv("USE_PROJECTION_FASTPATH", "false").lower() in {
    "1", "true", "yes", "y"
}
# If <=0, QuWARTS passes all inferred columns in a single LLM call per document.
PROJECTION_FASTPATH_COL_BATCH_SIZE = int(
    os.getenv("PROJECTION_FASTPATH_COL_BATCH_SIZE", "0")
)

# Caching
ENABLE_CACHE = True
CACHE_TTL = 86400  # 24 hours in seconds

# ============================================================================
# Validation Configuration
# ============================================================================

# Data validation
MAX_NULL_RATIO = 0.5  # max ratio of null values in a column
MIN_RECORDS_PER_TABLE = 1  # minimum records to create table

# ============================================================================
# Helper Functions
# ============================================================================

def get_dataset_path(dataset: str) -> Path:
    """Path to a dataset's source documents."""
    return SOURCE_DATA_DIR / dataset
