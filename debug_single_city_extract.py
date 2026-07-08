"""
Debug helper: run WDIRS extractor on one city source file.

Usage:
  python3 systems/WDIRS/debug_single_city_extract.py --file source_data/Player/city/1.txt
"""

import argparse
import json
import time
from pathlib import Path

from extractor import ConstrainedExtractor


def main() -> int:
    parser = argparse.ArgumentParser(description="Debug single city extraction")
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("source_data/Player/city/1.txt"),
        help="Path to one city source text file",
    )
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Print the generated extraction prompt",
    )
    parser.add_argument(
        "--max-chars",
        type=int,
        default=0,
        help="Optionally truncate source text to first N chars (0 = full file)",
    )
    args = parser.parse_args()

    file_path = args.file
    if not file_path.is_absolute():
        # Resolve from repo root (script is typically run from repo root)
        file_path = (Path.cwd() / file_path).resolve()

    if not file_path.exists():
        print(f"ERROR: file not found: {file_path}")
        return 1

    text = file_path.read_text(errors="ignore")
    if not text.strip():
        print(f"ERROR: empty file: {file_path}")
        return 1
    if args.max_chars and args.max_chars > 0:
        text = text[: args.max_chars]

    schema = {
        "city_name": "GPE",
        "state_name": "GPE",
        "population": "QUANTITY",
        "area": "QUANTITY",
        "gdp": "MONEY",
    }

    extractor = ConstrainedExtractor()

    # Build the same single-chunk prompt used in extraction path.
    prompt = extractor._build_extraction_prompt(
        chunk=text,
        table_name="city",
        schema=schema,
        constrained_keys=set(schema.keys()),
        normalization_hints=None,
        entity_col=None,
    )

    if args.show_prompt:
        print("=== PROMPT START ===")
        print(prompt)
        print("=== PROMPT END ===")

    print(f"File: {file_path}")
    print(f"Chars: {len(text)}")

    # Raw LLM response (first pass)
    raw = extractor.llm_client.generate(prompt)
    print("\n=== RAW LLM RESPONSE (first pass) ===")
    print(raw[:4000] + ("...<truncated>" if len(raw) > 4000 else ""))

    parse_keys = list(schema.keys())
    print("\n=== PARSED RECORDS (with repair fallback) ===")
    try:
        records = extractor._parse_extraction_response(
            raw,
            constrained_keys=set(schema.keys()),
            expected_keys=parse_keys,
        )
    except ValueError as e:
        print(f"First-parse failed: {e}")
        repaired = extractor._repair_extraction_response(raw, parse_keys)
        print("\n=== REPAIRED RESPONSE ===")
        print(repaired[:4000] + ("...<truncated>" if len(repaired) > 4000 else ""))
        records = extractor._parse_extraction_response(
            repaired,
            constrained_keys=set(schema.keys()),
            expected_keys=parse_keys,
        )

    normalized = extractor._normalize_records_for_schema(records, schema)
    print(json.dumps(normalized, indent=2, ensure_ascii=False))
    print(f"\nRecord count: {len(normalized)}")

    # Also run through extract_batch path (projection fast path behavior)
    print("\n=== extract_batch path (single doc) ===")
    chunk_id = f"debug::city::{file_path.stem}::{int(time.time())}"
    results = extractor.extract_batch(
        chunks=[text],
        chunk_ids=[chunk_id],
        table_name="city",
        schema=schema,
        constrained_keys=set(schema.keys()),
        normalization_hints=None,
        entity_col=None,
        col_batch_size_override=len(schema),
    )
    if not results:
        print("No ExtractionResult returned.")
        return 0

    er = results[0]
    print(f"chunk_id={er.chunk_id}")
    print(f"error={er.error}")
    print(f"records={json.dumps(er.records, indent=2, ensure_ascii=False)}")
    print(f"record_count={len(er.records)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

