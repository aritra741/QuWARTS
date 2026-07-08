import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Iterable, List, Set, Tuple


def normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def to_string_list(value) -> List[str]:
    """Convert scalar / JSON-list string / python list-like into string values."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]

    s = str(value).strip()
    if not s:
        return []

    # If model produced JSON array-like strings, unwrap them.
    if s.startswith("[") and s.endswith("]"):
        try:
            parsed = json.loads(s)
            if isinstance(parsed, list):
                out = []
                for x in parsed:
                    xs = str(x).strip()
                    if xs:
                        out.append(xs)
                return out
        except Exception:
            pass

    return [s]


def normalized_candidates(value) -> Set[str]:
    out: Set[str] = set()
    for v in to_string_list(value):
        n = normalize_text(v)
        if n:
            out.add(n)
    return out


def fetch_column(conn: sqlite3.Connection, table: str, col: str) -> List:
    cur = conn.execute(f"SELECT {col} FROM {table} WHERE {col} IS NOT NULL")
    return [row[0] for row in cur.fetchall()]


def count_exact_join(conn: sqlite3.Connection) -> int:
    cur = conn.execute(
        "SELECT COUNT(*) FROM player p JOIN team t ON p.team = t.team_name"
    )
    return int(cur.fetchone()[0])


def main() -> int:
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("quwarts (3).db")
    if not db_path.exists():
        print(f"DB not found: {db_path}")
        return 1

    conn = sqlite3.connect(str(db_path))
    try:
        player_vals = fetch_column(conn, "player", "team")
        team_vals = fetch_column(conn, "team", "team_name")
        exact_join = count_exact_join(conn)

        right_norm_set: Set[str] = set()
        for v in team_vals:
            right_norm_set.update(normalized_candidates(v))

        player_row_aligned = 0
        for v in player_vals:
            if normalized_candidates(v) & right_norm_set:
                player_row_aligned += 1

        left_distinct = sorted({str(v).strip() for v in player_vals if str(v).strip()})
        right_distinct = sorted({str(v).strip() for v in team_vals if str(v).strip()})

        left_distinct_aligned = 0
        unresolved_left: List[str] = []
        for raw in left_distinct:
            if normalized_candidates(raw) & right_norm_set:
                left_distinct_aligned += 1
            else:
                unresolved_left.append(raw)

        print("=== Join Alignment Analysis (player.team <-> team.team_name) ===")
        print(f"DB: {db_path}")
        print(f"Exact SQL join matches (current): {exact_join}")
        print()
        print(f"player.team non-null rows: {len(player_vals)}")
        print(f"team.team_name non-null rows: {len(team_vals)}")
        print(f"player.team distinct raw values: {len(left_distinct)}")
        print(f"team.team_name distinct raw values: {len(right_distinct)}")
        print(f"team.team_name distinct normalized tokens: {len(right_norm_set)}")
        print()
        print(
            "After normalization + list-unwrapping:"
            f" alignable player rows = {player_row_aligned}/{len(player_vals)}"
        )
        print(
            "After normalization + list-unwrapping:"
            f" alignable player distinct keys = {left_distinct_aligned}/{len(left_distinct)}"
        )
        print()
        print("Sample unresolved player.team raw values (up to 20):")
        for v in unresolved_left[:20]:
            print(f"  - {v}")

        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())

