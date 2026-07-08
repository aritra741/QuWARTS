#!/usr/bin/env python3
"""
Run QuWARTS preprocessing for Player.owner table only.

This script builds an owner-only workload query (no joins), runs preprocessing,
and prints a compact quality snapshot for the resulting `owner` table.

Usage:
  cd QuWARTS
  ../../.venv/bin/python test_owner_only_preprocess.py
  ../../.venv/bin/python test_owner_only_preprocess.py --db "./quwarts-owner-only.db" --fresh
"""

import argparse
import csv
import json
import logging
from pathlib import Path
import sys

# Local imports from QuWARTS
QUWARTS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = QUWARTS_ROOT.parent.parent
if str(QUWARTS_ROOT) not in sys.path:
    sys.path.insert(0, str(QUWARTS_ROOT))

from quwarts_runner import QuWARTSRunner

logger = logging.getLogger(__name__)


def setup_logging(log_file: Path) -> None:
    """Write logs to both console and a dedicated file."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    # Prevent duplicate log lines from prior/basicConfig handlers.
    for h in list(root.handlers):
        root.removeHandler(h)

    fmt = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    fh = logging.FileHandler(log_file)
    ch = logging.StreamHandler(sys.stdout)
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)
    root.addHandler(fh)
    root.addHandler(ch)


def build_owner_only_query() -> str:
    """
    Build one explicit owner-only query from GT CSV headers.
    Excludes ID so identity extraction focuses on semantic fields.
    """
    csv_path = PROJECT_ROOT / "Data" / "Player" / "owner.csv"
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)

    cols = [c.strip().strip('"') for c in header if c.strip()]
    cols = [c for c in cols if c.lower() != "id"]
    if not cols:
        cols = ["name", "age", "nationality", "nba_team", "own_year"]

    return "SELECT " + ", ".join(cols) + " FROM owner;"


def print_owner_snapshot(runner: QuWARTSRunner) -> None:
    """
    Print owner table quality indicators:
    - row count + distinct name count
    - sample names
    - provenance source prefixes for name cells
    """
    if not runner.data_layer.table_exists("owner"):
        print("owner table does not exist after preprocessing.")
        return

    rows = runner.data_layer.get_all_records("owner")
    names = [str(r.get("name") or "").strip() for r in rows if str(r.get("name") or "").strip()]
    distinct_names = sorted(set(names))

    print("\n=== owner snapshot ===")
    print(f"rows: {len(rows)}")
    print(f"distinct names: {len(distinct_names)}")
    print("sample names:", distinct_names[:12])

    # Source contamination check via cell_provenance on owner.name
    q = """
    SELECT
      CASE
        WHEN instr(doc_id, '/') > 0 THEN substr(doc_id, 1, instr(doc_id, '/') - 1)
        ELSE doc_id
      END AS source_prefix,
      COUNT(*) AS cnt
    FROM cell_provenance cp
    JOIN owner o ON o.row_id = cp.row_id
    WHERE cp.column_name = 'name'
    GROUP BY source_prefix
    ORDER BY cnt DESC
    """
    pref_rows = runner.data_layer.execute_sql(q)
    print("name provenance prefixes:", pref_rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="Preprocess only Player.owner table")
    ap.add_argument(
        "--dataset",
        default="Player",
        help="Dataset name (default: Player)",
    )
    ap.add_argument(
        "--db",
        default=str(QUWARTS_ROOT / "quwarts-owner-only.db"),
        help="Output sqlite DB path (default: quwarts-owner-only.db)",
    )
    ap.add_argument(
        "--fresh",
        action="store_true",
        help="Delete existing DB file before run",
    )
    ap.add_argument(
        "--log",
        default=str(QUWARTS_ROOT / "owner_only_preprocess.log"),
        help="Log file path (default: owner_only_preprocess.log)",
    )
    args = ap.parse_args()

    log_path = Path(args.log).resolve()
    setup_logging(log_path)
    logger.info(f"Owner-only preprocess log: {log_path}")

    db_path = Path(args.db).resolve()
    if args.fresh and db_path.exists():
        db_path.unlink()
        logger.info(f"Deleted existing DB: {db_path}")

    workload_query = build_owner_only_query()
    logger.info(f"owner-only workload query: {workload_query}")

    runner = QuWARTSRunner(dataset=args.dataset, postgres_uri=f"sqlite:///{db_path}")
    result = runner.preprocess(workload_queries=[workload_query])

    logger.info("=== preprocess result ===")
    logger.info(json.dumps(
        {
            "success": result.success,
            "tables_processed": result.tables_processed,
            "total_chunks": result.total_chunks,
            "total_records": result.total_records,
            "preprocessing_time_sec": round(result.preprocessing_time, 2),
            "error": result.error,
            "db_path": str(db_path),
        },
        indent=2,
    ))

    if result.success:
        print_owner_snapshot(runner)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
