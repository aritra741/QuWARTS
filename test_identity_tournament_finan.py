#!/usr/bin/env python3
"""
Test tournament-style identity column detection using real schema from Finan.csv.

Loads column names from Data/Finan/Finan.csv (excluding the id column), runs
detect_identity_column() in tournament mode, and checks that the LLM-selected
champion is the expected primary identity column (company_name for Finance).

Usage:
  cd QuWARTS && python test_identity_tournament_finan.py
  python test_identity_tournament_finan.py --csv /path/to/Finan.csv
  python test_identity_tournament_finan.py --expected company_name
"""

import argparse
import csv
import logging
import sys
from pathlib import Path
from typing import List

# Run from QuWARTS directory so local imports work
QUWARTS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = QUWARTS_ROOT.parent.parent
if str(QUWARTS_ROOT) not in sys.path:
    sys.path.insert(0, str(QUWARTS_ROOT))

# Log tournament rounds and result
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
    stream=sys.stdout,
)

# Default path to Finan ground-truth CSV (columns = real schema, minus id)
DEFAULT_FINAN_CSV = PROJECT_ROOT / "Data" / "Finan" / "Finan.csv"
# For Finance/Finan dataset the primary identity column is company_name
EXPECTED_IDENTITY_FINAN = "company_name"


def load_columns_and_samples(
    csv_path: Path,
    exclude_id: bool = True,
    n_sample_rows: int = 5,
) -> tuple:
    """
    Read column names and a small set of sample values from a CSV.

    Returns (columns, sample_values) where:
      - columns      : list of column names (excluding 'id' if exclude_id)
      - sample_values: dict {column_name: [val1, val2, ...]} with up to
                       n_sample_rows non-empty values per column
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        field_names = reader.fieldnames or []
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) >= n_sample_rows:
                break

    columns = [c.strip() for c in field_names if c.strip()]
    if exclude_id:
        columns = [c for c in columns if c.lower() != "id"]

    sample_values: dict = {}
    for col in columns:
        vals = [row.get(col, "").strip() for row in rows if row.get(col, "").strip()]
        sample_values[col] = vals[:n_sample_rows]

    return columns, sample_values


def main():
    ap = argparse.ArgumentParser(
        description="Test tournament identity detection with Finan.csv columns"
    )
    ap.add_argument(
        "--csv",
        type=Path,
        default=DEFAULT_FINAN_CSV,
        help=f"Path to Finan CSV (default: {DEFAULT_FINAN_CSV})",
    )
    ap.add_argument(
        "--expected",
        default=EXPECTED_IDENTITY_FINAN,
        help=f"Expected identity column (default: {EXPECTED_IDENTITY_FINAN})",
    )
    ap.add_argument(
        "--no-exclude-id",
        action="store_true",
        help="Do not exclude column named 'id' from the schema",
    )
    args = ap.parse_args()

    if not args.csv.exists():
        print(f"Error: CSV not found: {args.csv}", file=sys.stderr)
        return 2

    schema_columns, sample_values = load_columns_and_samples(
        args.csv, exclude_id=not args.no_exclude_id
    )
    if not schema_columns:
        print("Error: No columns found in CSV", file=sys.stderr)
        return 2

    table_name = "finance"
    print(f"Table: {table_name}")
    print(f"CSV: {args.csv}")
    print(f"Columns ({len(schema_columns)}): {schema_columns}")
    print(f"Sample rows per column: {len(next(iter(sample_values.values()), []))}")
    print(f"Expected identity column: {args.expected}")
    print()

    from entity_anchor import TOURNAMENT_GROUP_SIZE, detect_identity_column
    from extractor import OllamaClient

    client = OllamaClient()
    result = detect_identity_column(
        table_name,
        schema_columns,
        client,
        group_size=TOURNAMENT_GROUP_SIZE,
        sample_values=sample_values,
    )

    print()
    print(f"Result: {result!r}")
    print(f"Expected: {args.expected!r}")
    passed = result is not None and result == args.expected
    print(f"Pass: {passed}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
