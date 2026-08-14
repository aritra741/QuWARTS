"""
QuWARTS: Query Workload Aware Relational Table Synthesis from Unstructured Text.
"""

from typing import Any

__version__ = "1.0.0"
__all__ = ["QuWARTSRunner", "PreprocessingResult", "QueryResult"]


def __getattr__(name: str) -> Any:
    if name in {"QuWARTSRunner", "PreprocessingResult", "QueryResult"}:
        from .runner import PreprocessingResult, QueryResult, QuWARTSRunner

        mapping = {
            "QuWARTSRunner": QuWARTSRunner,
            "PreprocessingResult": PreprocessingResult,
            "QueryResult": QueryResult,
        }
        return mapping[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
