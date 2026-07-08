#!/usr/bin/env python3
"""
Standalone test for identity-column detection prompts.

Runs detect_identity_column() against known schemas and reports whether
the LLM returns the expected identity column. No domain hints are
injected — the prompts use only structural descriptions.

Usage:
  cd QuWARTS && python test_identity_prompt.py
  python test_identity_prompt.py --table player --expected player_name
  python test_identity_prompt.py --show-prompts   # print prompts only, no LLM call
"""

import argparse
import logging
import sys
from pathlib import Path

# Run from QuWARTS directory so local imports work
QUWARTS_ROOT = Path(__file__).resolve().parent
if str(QUWARTS_ROOT) not in sys.path:
    sys.path.insert(0, str(QUWARTS_ROOT))

# Minimal logging so entity_anchor messages are visible
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(name)s - %(message)s",
    stream=sys.stdout,
)

# Schema fixtures (Tier-1 entity candidates as in production — PERSON/ORG/GPE columns)
FINANCE_SCHEMA = [
    "auditor",
    "major_equity_changes",
    "board_members",
    "registered_office",
    "largest_shareholder",
    "company_name",
    "executive_profiles",
]

PLAYER_SCHEMA = [
    "player_name",
    "team",
    "position",
    "nationality",
]

MEDICAL_SCHEMA = [
    "patient_id",
    "diagnosis",
    "doctor_name",
    "hospital",
]

FIXTURES = {
    "finance": (FINANCE_SCHEMA, "company_name"),
    "player": (PLAYER_SCHEMA, "player_name"),
    "medical": (MEDICAL_SCHEMA, "patient_id"),
}


def build_prompts(table_name: str, schema_columns: list) -> tuple:
    """Build the same prompt strings used in entity_anchor.detect_identity_column."""
    col_lower = {c.lower(): c for c in schema_columns}
    bullet_list = "\n".join(f"  - {c}" for c in schema_columns)

    prompt1 = (
        f"A relational table called '{table_name}' contains these candidate "
        f"columns:\n{bullet_list}\n\n"
        f"In any well-structured table, exactly one column serves as the "
        f"subject identifier: its value tells you WHICH entity the row is "
        f"about, while every other column describes a property of that entity.\n\n"
        f"Which column from the list above is the subject identifier?\n"
        f"Respond with ONLY the exact column name. You must pick one."
    )

    prompt2 = (
        f"Table: '{table_name}'\n"
        f"Columns: {schema_columns}\n\n"
        f"One column is the anchor of every row — removing it would make "
        f"the row unidentifiable. All other columns are attributes that only "
        f"make sense once you know which row you are looking at.\n\n"
        f"Which column is the anchor?\n"
        f"Respond with ONLY the exact column name. You must pick one."
    )

    return prompt1, prompt2


def main():
    ap = argparse.ArgumentParser(description="Test identity-column detection prompts")
    ap.add_argument(
        "--table",
        choices=list(FIXTURES),
        default="finance",
        help="Schema fixture to use (default: finance)",
    )
    ap.add_argument(
        "--expected",
        default=None,
        help="Expected identity column (default: from fixture)",
    )
    ap.add_argument(
        "--show-prompts",
        action="store_true",
        help="Print prompts only; do not call the LLM",
    )
    args = ap.parse_args()

    schema_columns, default_expected = FIXTURES[args.table]
    expected = args.expected or default_expected

    print(f"Table: {args.table}")
    print(f"Schema columns ({len(schema_columns)}): {schema_columns}")
    print(f"Expected identity column: {expected}")
    print()

    if args.show_prompts:
        p1, p2 = build_prompts(args.table, schema_columns)
        print("--- Prompt 1 (Attempt 1) ---")
        print(p1)
        print()
        print("--- Prompt 2 (Attempt 2, if Attempt 1 fails) ---")
        print(p2)
        return 0

    from entity_anchor import detect_identity_column
    from extractor import OllamaClient

    client = OllamaClient()
    result = detect_identity_column(args.table, schema_columns, client)

    print(f"Result: {result!r}")
    print(f"Expected: {expected!r}")
    passed = result == expected
    print(f"Pass: {passed}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
