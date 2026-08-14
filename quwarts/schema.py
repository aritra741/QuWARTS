"""SQL type mapping for workload-inferred semantic types."""

from typing import Dict

SEMANTIC_TO_SQL: Dict[str, str] = {
    "PERSON": "TEXT",
    "ORG": "TEXT",
    "DATE": "TEXT",
    "GPE": "TEXT",
    "CODE": "TEXT",
    "MONEY": "REAL",
    "QUANTITY": "REAL",
    "QUANTITY_COUNT": "REAL",
    "PRODUCT": "TEXT",
    "EVENT": "TEXT",
    "OTHER": "TEXT",
}

NUMERIC_SQL_TYPES = {"REAL", "INTEGER", "NUMERIC", "INT", "FLOAT", "DOUBLE"}


def semantic_to_sql_type(semantic_type: str) -> str:
    """Map a lattice semantic type to a SQLite column type."""
    return SEMANTIC_TO_SQL.get(semantic_type, "TEXT")
