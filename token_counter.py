"""
Token Counter for WDIRS — Qwen2.5-7B-Instruct tokenizer.

Provides a process-wide singleton (GLOBAL_COUNTER) that accumulates input and
output token counts for every LLM call made through OllamaClient.generate().
Tokens are attributed to the calling component (extractor, entity_anchor,
lattice_planner, etc.) by inspecting the Python call stack.

Uses transformers.AutoTokenizer which respects standard HF cache env vars:
- HF_HOME
- HUGGINGFACE_HUB_CACHE
- TRANSFORMERS_CACHE

Usage
-----
    from token_counter import GLOBAL_COUNTER
    GLOBAL_COUNTER.record(input_tokens=42, output_tokens=17, operation="extraction")
    print(GLOBAL_COUNTER.summary_str())
"""

import inspect
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Qwen2.5-7B-Instruct tokenizer — loaded once, shared across all threads
# ---------------------------------------------------------------------------

_tokenizer = None
_tokenizer_failed = False
_tokenizer_name = "uninitialized"
_tokenizer_lock = threading.Lock()


def _load_tokenizer():
    """Load Qwen2.5-7B-Instruct tokenizer using transformers (respects HF_HOME etc)."""
    global _tokenizer, _tokenizer_failed, _tokenizer_name
    if _tokenizer is not None:
        return _tokenizer
    if _tokenizer_failed:
        return None

    with _tokenizer_lock:
        if _tokenizer is not None:
            return _tokenizer
        if _tokenizer_failed:
            return None

        try:
            from transformers import AutoTokenizer

            _tokenizer = AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B-Instruct")
            _tokenizer_name = "Qwen2.5-7B-Instruct (from_pretrained)"
            logger.info(
                f"[TokenCounter] Loaded Qwen2.5-7B-Instruct tokenizer via transformers"
            )
            return _tokenizer
        except Exception as exc:
            _tokenizer_failed = True
            hf_home = os.getenv("HF_HOME", "~/.cache/huggingface")
            hf_cache = os.getenv("HUGGINGFACE_HUB_CACHE", f"{hf_home}/hub")
            raise RuntimeError(
                f"[TokenCounter] Precise tokenization required, but Qwen tokenizer could not be loaded.\n"
                f"Reason: {exc}\n\n"
                f"Fix: Download the tokenizer with:\n"
                f"  python3 -c 'from transformers import AutoTokenizer; "
                f"AutoTokenizer.from_pretrained(\"Qwen/Qwen2.5-7B-Instruct\"); print(\"OK\")'\n\n"
                f"Cache location (will be used):\n"
                f"  HF_HOME={hf_home}\n"
                f"  HUGGINGFACE_HUB_CACHE={hf_cache}\n\n"
                f"Or set these env vars to use a custom cache location:\n"
                f"  export HF_HOME=/path/to/cache\n"
                f"  export HUGGINGFACE_HUB_CACHE=/path/to/cache/hub"
            )


def count_tokens(text: str) -> int:
    """Return the number of Qwen2.5-7B-Instruct tokens in *text*."""
    if not text:
        return 0
    tok = _load_tokenizer()
    if tok is None:
        raise RuntimeError(
            "[TokenCounter] Precise tokenization required, but tokenizer is unavailable."
        )
    encoded = tok.encode(text)
    if hasattr(encoded, "__len__"):
        return len(encoded)
    return len(list(encoded))


def ensure_precise_tokenizer_ready() -> None:
    """Fail-fast check for strict token counting setups."""
    _load_tokenizer()


# ---------------------------------------------------------------------------
# Operation attribution — map call-stack frame to a readable label
# ---------------------------------------------------------------------------

# Module-name substrings → human-readable operation label (first match wins)
_MODULE_LABELS = [
    ("sieve_synthesizer", "sieve_synthesis"),
    ("entity_anchor", "entity_anchor"),
    ("entity_resolver", "entity_resolution"),
    ("lattice_planner", "lattice_planner"),
    ("delta_engine", "runtime_delta"),
    ("wdirs_runner", "runner"),
    ("extractor", "extraction"),
]


def _infer_operation() -> str:
    """
    Walk the call stack (skipping token_counter and extractor frames) and
    return a label for the first recognisable WDIRS module found.
    """
    for frame_info in inspect.stack():
        filename = frame_info.filename or ""
        for substring, label in _MODULE_LABELS:
            if substring in filename:
                return label
    return "unknown"


# ---------------------------------------------------------------------------
# Thread-safe token counter
# ---------------------------------------------------------------------------


@dataclass
class _OperationStats:
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


class TokenCounter:
    """
    Process-wide, thread-safe accumulator for Qwen2.5 token usage.

    Attributes
    ----------
    input_tokens  : total prompt tokens sent to the LLM
    output_tokens : total completion tokens received
    total_tokens  : input_tokens + output_tokens
    call_count    : number of LLM calls recorded
    by_operation  : per-operation breakdown (dict of _OperationStats)
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.call_count: int = 0
        self.by_operation: Dict[str, _OperationStats] = {}
        self._start_time: float = time.time()

    # ------------------------------------------------------------------
    def record(
        self,
        input_tokens: int,
        output_tokens: int,
        operation: Optional[str] = None,
    ) -> None:
        """
        Add *input_tokens* and *output_tokens* to the running totals.

        Parameters
        ----------
        input_tokens  : number of prompt tokens in this call
        output_tokens : number of completion tokens in this call
        operation     : label for the calling component; inferred from the
                        call stack when None
        """
        if operation is None:
            operation = _infer_operation()

        with self._lock:
            self.input_tokens += input_tokens
            self.output_tokens += output_tokens
            self.call_count += 1

            stats = self.by_operation.setdefault(operation, _OperationStats())
            stats.calls += 1
            stats.input_tokens += input_tokens
            stats.output_tokens += output_tokens
            stats.total_tokens += input_tokens + output_tokens

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    # ------------------------------------------------------------------
    def summary_dict(self) -> dict:
        elapsed = time.time() - self._start_time
        ops = {
            op: {
                "calls": s.calls,
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "total_tokens": s.total_tokens,
            }
            for op, s in sorted(
                self.by_operation.items(),
                key=lambda kv: kv[1].total_tokens,
                reverse=True,
            )
        }
        return {
            "model": "qwen2.5:7b-instruct",
            "tokenizer": _tokenizer_name,
            "elapsed_seconds": round(elapsed, 1),
            "llm_calls": self.call_count,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "by_operation": ops,
        }

    def summary_str(self) -> str:
        d = self.summary_dict()
        lines = [
            "",
            "=" * 70,
            "  TOKEN COST SUMMARY  —  Qwen2.5-7B-Instruct",
            "=" * 70,
            f"  Model         : {d['model']}",
            f"  Tokenizer     : {d['tokenizer']}",
            f"  Elapsed       : {d['elapsed_seconds']}s",
            f"  LLM calls     : {d['llm_calls']:,}",
            f"  Input tokens  : {d['input_tokens']:,}",
            f"  Output tokens : {d['output_tokens']:,}",
            f"  TOTAL tokens  : {d['total_tokens']:,}",
            "",
            "  Breakdown by operation:",
        ]
        for op, stats in d["by_operation"].items():
            lines.append(
                f"    {op:<22}  calls={stats['calls']:>5,}  "
                f"in={stats['input_tokens']:>9,}  "
                f"out={stats['output_tokens']:>8,}  "
                f"total={stats['total_tokens']:>9,}"
            )
        lines.append("=" * 70)
        return "\n".join(lines)

    def save_json(self, path) -> None:
        """Write the summary dict as JSON to *path*."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as fh:
            json.dump(self.summary_dict(), fh, indent=2)
        logger.info(f"[TokenCounter] Token cost saved to {path}")

    def reset(self) -> None:
        with self._lock:
            self.input_tokens = 0
            self.output_tokens = 0
            self.call_count = 0
            self.by_operation.clear()
            self._start_time = time.time()


# ---------------------------------------------------------------------------
# Module-level singleton — import and use this everywhere
# ---------------------------------------------------------------------------

GLOBAL_COUNTER = TokenCounter()
