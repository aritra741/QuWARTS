#!/usr/bin/env python3
"""
Run a single SQL query and compare our output against ground truth.

Usage:
  python run_one_query.py

Uses latest Player DB by date from test_player_workload.py output
(results/player_workload_preprocess/run_*/Player_preprocessed.db).
Ground truth: Data/Player/player.db.
"""

import sqlite3
import sys
import time
from pathlib import Path
from typing import Optional

# Match test_player_query_awareness_trend.py
sys.path.insert(0, str(Path(__file__).parent))
from config import PROJECT_ROOT, RESULTS_DIR

GROUND_TRUTH_DIR = PROJECT_ROOT / "Data" / "Player"
GOLD_DB = GROUND_TRUTH_DIR / "player.db"
PREPROCESS_BASE = RESULTS_DIR / "player_workload_preprocess"


def _find_latest_our_db() -> Optional[Path]:
    """Latest Player_preprocessed.db by run dir name (run_YYYYMMDD_HHMMSS)."""
    if not PREPROCESS_BASE.exists():
        return None
    runs = sorted(
        (d for d in PREPROCESS_BASE.glob("run_*") if d.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    for run_dir in runs:
        db = run_dir / "Player_preprocessed.db"
        if db.exists():
            return db
    return None

QUERY = """
SELECT t.team_name, t.location,
       COUNT(p.name) as player_count
FROM player p
JOIN team t ON p.team = t.team_name
WHERE p.draft_year > 2000
   OR p.position = 'Frontcourt'
   OR t.founded_year < 1980
GROUP BY t.team_name, t.location, t.founded_year;
"""

KEY_COLS = ["team_name", "location"]


def _row_key(row: dict, key_cols: list) -> tuple:
    return tuple(
        "" if c not in row or row[c] is None else str(row[c]).strip().lower()
        for c in key_cols
    )


def run_query(conn: sqlite3.Connection, query: str) -> tuple[list[dict], list[str], float]:
    """Execute query, return (rows as dicts, column names, elapsed seconds)."""
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    t0 = time.perf_counter()
    cur.execute(query)
    rows = cur.fetchall()
    elapsed = time.perf_counter() - t0
    col_names = [d[0] for d in cur.description]
    return [dict(zip(col_names, r)) for r in rows], col_names, elapsed


def main() -> int:
    gold_path = GOLD_DB.resolve()
    our_path = _find_latest_our_db()
    if our_path is None:
        print(
            f"No preprocessed DB found. Run test_player_workload.py first.\n"
            f"Expected: {PREPROCESS_BASE}/run_*/Player_preprocessed.db"
        )
        return 1
    our_path = our_path.resolve()

    if not gold_path.exists():
        print(f"Gold database not found: {gold_path}")
        return 1

    conn_gold = sqlite3.connect(str(gold_path))
    gold_rows, col_names, gold_time = run_query(conn_gold, QUERY)
    conn_gold.close()

    conn_our = sqlite3.connect(str(our_path))
    our_rows, _, our_time = run_query(conn_our, QUERY)
    conn_our.close()

    print("\n" + "=" * 70)
    print("Query: player_count by team (draft_year>2000 OR position='Frontcourt' OR founded_year<1980)")
    print("=" * 70)

    gold_map = {_row_key(r, KEY_COLS): r for r in gold_rows}
    our_map = {_row_key(r, KEY_COLS): r for r in our_rows}
    gold_keys = set(gold_map)
    our_keys = set(our_map)

    matched = gold_keys & our_keys
    extra = our_keys - gold_keys
    missed = gold_keys - our_keys

    print("\n--- Our output ---")
    print("  ".join(f"{c:>20}" for c in col_names))
    print("-" * 70)
    for r in our_rows:
        print("  ".join(f"{str(r[c]):>20}" for c in col_names))
    print("-" * 70)

    print("\n--- Comparison ---")
    print(f"  Matched:  {len(matched)}")
    print(f"  Extra:    {len(extra)}   (in our output, not in gold)")
    print(f"  Missed:   {len(missed)}   (in gold, not in our output)")
    print(f"\n--- Time ---")
    print(f"  Gold DB:  {gold_time:.4f}s")
    print(f"  Our DB:   {our_time:.4f}s")

    if extra:
        print(f"\n  Extra rows (team_name, location): {[(k[0], k[1]) for k in sorted(extra)]}")
    if missed:
        print(f"  Missed rows (team_name, location): {[(k[0], k[1]) for k in sorted(missed)]}")

    return 0


if __name__ == "__main__":
    exit(main())
