#!/usr/bin/env python3
"""
Test: feed a full document to the LLM and ask for company_name values
(document-level entity discovery for Pass 1; identity column is already
known to be company_name before extraction).

qwen2.5:7b-instruct supports 128k tokens, so the full document is sent.

Usage (use project venv):
  cd QuWARTS && ../../.venv/bin/python test_doc_entity_discovery.py
  ../../.venv/bin/python test_doc_entity_discovery.py --doc path/to/document.txt
"""

import argparse
import json
import re
import sys
from pathlib import Path

# Run from QuWARTS directory so local imports work
QUWARTS_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = QUWARTS_ROOT.parent.parent
if str(QUWARTS_ROOT) not in sys.path:
    sys.path.insert(0, str(QUWARTS_ROOT))

# Default: one Finance annual report
DEFAULT_DOC = PROJECT_ROOT / "source_data" / "Finance" / "finance" / "1.txt"

SYSTEM_PROMPT = (
    "You are a JSON-only extraction assistant. "
    "Output ONLY a raw JSON array — no explanation, no markdown, no code fences."
)

# Pass 1: full document → summary/prose (model may ignore JSON format on long input)
PASS1_PROMPT_TEMPLATE = """\
What company or companies is the following document about?
Output ONLY a raw JSON array of company name strings, e.g.: ["Acme Corp"]
No other text.

Document:
---
{document}
---
[\""""

# Pass 2: short prose summary from Pass 1 → clean JSON extraction
PASS2_PROMPT_TEMPLATE = """\
Extract the company name(s) from the following text and return them as a raw JSON array.
Output ONLY the JSON array, e.g.: ["Acme Corp"]
No other text.

Text:
---
{summary}
---
[\""""


def _extract_json_array(text: str):
    """
    Extract the first JSON array from the response, tolerating any surrounding
    prose or markdown the model may have added despite instructions.
    The prompt primes the model with [" so prepend it when parsing.
    """
    # Model continues from the primed [" — prepend it for parsing
    candidates = [
        '["' + text.strip(),   # primed continuation
        text.strip(),           # raw response
    ]
    for raw in candidates:
        try:
            val = json.loads(raw)
            if isinstance(val, list):
                return val
        except json.JSONDecodeError:
            pass

    # Fallback: find the first [...] block anywhere in the combined text
    combined = '["' + text
    match = re.search(r'\[.*?\]', combined, re.DOTALL)
    if match:
        try:
            val = json.loads(match.group())
            if isinstance(val, list):
                return val
        except json.JSONDecodeError:
            pass

    return None


def main():
    ap = argparse.ArgumentParser(
        description="Feed a full document to the LLM and extract company_name values"
    )
    ap.add_argument(
        "--doc",
        type=Path,
        default=DEFAULT_DOC,
        help=f"Path to document (default: {DEFAULT_DOC})",
    )
    ap.add_argument(
        "--max-tokens",
        type=int,
        default=128,
        help="Max tokens for LLM response (default: 128)",
    )
    args = ap.parse_args()

    doc_path = args.doc
    if not doc_path.is_file():
        print(f"Error: file not found: {doc_path}", file=sys.stderr)
        sys.exit(1)

    text = doc_path.read_text(encoding="utf-8", errors="replace")
    print(
        f"Document: {doc_path.name}, {len(text)} chars (~{len(text)//4} tokens)",
        file=sys.stderr,
    )
    print("Calling LLM...", file=sys.stderr)

    try:
        from extractor import OllamaClient
    except ImportError as e:
        print(
            f"Import error: {e}. Activate the project venv first.",
            file=sys.stderr,
        )
        sys.exit(1)

    client = OllamaClient()

    # Pass 1: full document → try to get JSON directly
    print("Pass 1: full document → LLM...", file=sys.stderr)
    pass1_prompt = PASS1_PROMPT_TEMPLATE.format(document=text)
    pass1_response = client.generate(
        pass1_prompt,
        max_tokens=args.max_tokens,
        temperature=0.0,
        system_prompt=SYSTEM_PROMPT,
    )

    print("\n--- Pass 1 LLM response ---")
    print(pass1_response)
    print("--- end ---")

    companies = _extract_json_array(pass1_response)
    if companies is not None:
        print(f"\nPass 1 succeeded. {len(companies)} company_name(s): {companies}")
        return

    # Pass 2: model returned prose — extract company name from its own summary
    print("\nPass 1 returned prose. Pass 2: extracting company name from summary...", file=sys.stderr)
    pass2_prompt = PASS2_PROMPT_TEMPLATE.format(summary=pass1_response)
    pass2_response = client.generate(
        pass2_prompt,
        max_tokens=args.max_tokens,
        temperature=0.0,
        system_prompt=SYSTEM_PROMPT,
    )

    print("\n--- Pass 2 LLM response ---")
    print(pass2_response)
    print("--- end ---")

    companies = _extract_json_array(pass2_response)
    if companies is not None:
        print(f"\nPass 2 succeeded. {len(companies)} company_name(s): {companies}")
    else:
        print("\nBoth passes failed to produce a JSON array.", file=sys.stderr)


if __name__ == "__main__":
    main()
