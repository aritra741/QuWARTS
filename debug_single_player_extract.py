"""
Run one Player source document through WDIRS extraction with:
- workload-derived schema
- workload normalization hints
- current iterative long-document extraction path

Usage:
  .venv/bin/python systems/WDIRS/debug_single_player_extract.py \
      --file source_data/Player/player/119.txt
"""

import argparse
import json
from pathlib import Path
from typing import List

from lattice_planner import LatticePlanner
from extractor import ConstrainedExtractor


def _collect_sql_queries(query_root: Path) -> List[str]:
    queries: List[str] = []
    for sql_file in sorted(query_root.rglob("*.sql")):
        text = sql_file.read_text(errors="ignore")
        # Strip comment lines, then split on ';'
        cleaned_lines = []
        for line in text.splitlines():
            if line.strip().startswith("--"):
                continue
            cleaned_lines.append(line)
        cleaned = "\n".join(cleaned_lines)
        for part in cleaned.split(";"):
            q = part.strip()
            if q:
                queries.append(q + ";")
    return queries


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug single player extraction")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("source_data/Player/player/119.txt"),
        help="Player source text file path",
    )
    parser.add_argument(
        "--query-root",
        type=Path,
        default=Path("Query/Player"),
        help="Workload query root used to derive hints",
    )
    parser.add_argument(
        "--show-schema-and-hints",
        action="store_true",
        help="Print derived schema and normalization hints",
    )
    args = parser.parse_args()

    file_path = args.file.resolve() if not args.file.is_absolute() else args.file
    query_root = args.query_root.resolve() if not args.query_root.is_absolute() else args.query_root

    if not file_path.exists():
        print(f"ERROR: file not found: {file_path}")
        return 1
    if not query_root.exists():
        print(f"ERROR: query root not found: {query_root}")
        return 1

    text = file_path.read_text(errors="ignore")
    if not text.strip():
        print(f"ERROR: empty file: {file_path}")
        return 1

    queries = _collect_sql_queries(query_root)
    if not queries:
        print(f"ERROR: no SQL queries found under {query_root}")
        return 1

    extractor = ConstrainedExtractor()
    planner = LatticePlanner(extractor.llm_client)
    planner.parse_workload(queries, identify_types=True)

    table_name = "player"
    schema = planner.get_table_schema(table_name)
    if not schema:
        print("ERROR: no schema found for table 'player' from workload")
        return 1

    hints = planner.get_normalization_hints(table_name)
    constrained_keys = set(schema.keys())

    if args.show_schema_and_hints:
        print("=== Derived schema (player) ===")
        print(json.dumps(schema, indent=2))
        print("\n=== Derived normalization hints (player) ===")
        print(json.dumps(hints, indent=2))

    result = extractor._extract_single_chunk(
        chunk=text,
        table_name=table_name,
        schema=schema,
        constrained_keys=constrained_keys,
        normalization_hints=hints,
        entity_col=None,
    )

    print(f"File: {file_path}")
    print(f"Chars: {len(text)}")
    print(f"Schema columns: {len(schema)}")
    print(f"Hint columns: {len(hints)}")
    print(f"Error: {result.error}")
    print(f"Record count: {len(result.records)}")
    print("\n=== Extracted records ===")
    print(json.dumps(result.records, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

