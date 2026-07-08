"""
Run Q1..Q10 query-awareness trend evaluation on Player.

What this script does:
1) Snapshot previously created artifacts (DB/cache/extractions) once, if absent.
2) Execute Q1..Q10 trend queries on a working copy of the snapshot DB.
3) Save per-query result tables and metrics (latency, token counts, macro F1/P/R).
4) Generate plots with Q1..Q10 on the x-axis.
"""

import csv
import json
import logging
import re
import shutil
import sqlite3
import sys
import time
import argparse
import math
import unicodedata
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except Exception:
    MATPLOTLIB_AVAILABLE = False

import pandas as pd
import sqlglot
import sqlglot.expressions as _sqlglot_exp

# Add QuWARTS to path
sys.path.insert(0, str(Path(__file__).parent))

from token_counter import GLOBAL_COUNTER, ensure_precise_tokenizer_ready
from extractor import OllamaClient
from quwarts_runner import QuWARTSRunner
import config as config_module
from config import (
    CACHE_DIR,
    DB_DIR,
    PROJECT_ROOT,
    QUERY_DIR,
    RESULTS_DIR,
)

sys.path.insert(0, str(PROJECT_ROOT))
from evaluation.config import EvalSettings as _EvalSettings, load_json as _load_json
from evaluation.gt_runner import GtRunner as _GtRunner
from evaluation.metrics import MetricCalculator as _MetricCalculator
from evaluation.query_manifest import QueryManifest as _QueryManifest
from evaluation.result_writer import ResultWriter as _ResultWriter
from evaluation.row_matcher import RowMatcher as _RowMatcher
from evaluation.sql_parser import SqlParser as _SqlParser
from evaluation.utils import (
    add_missing_columns as _add_missing_cols,
    clean_string_columns as _clean_string_cols,
    drop_unnamed_columns as _drop_unnamed,
    normalize_file_name_columns as _norm_file_cols,
    normalize_types as _norm_types,
    standardize_column_name as _std_col,
)

logger = logging.getLogger(__name__)

DATASET = "Player"
DATASET_QUERY = "Player"
TREND_SQL_FILE = QUERY_DIR / DATASET_QUERY / "query_aware_trend_queries.sql"
GROUND_TRUTH_DIR = PROJECT_ROOT / "Data" / "Player"
ATTRIBUTES_FILE = PROJECT_ROOT / "Query" / DATASET_QUERY / "Player_attributes.json"
REDD_TREND_FILE = PROJECT_ROOT / "systems" / "ReDD" / "test_player_query_awareness_trend_redd.py"

# ReDD category query folders (used to mirror ReDD's uncommented query set)
QUERY_CATEGORY_DIRS: Dict[str, Path] = {
    "S": QUERY_DIR / DATASET_QUERY / "Select",
    "F": QUERY_DIR / DATASET_QUERY / "Filter",
    "A": QUERY_DIR / DATASET_QUERY / "Agg",
    "J": QUERY_DIR / DATASET_QUERY / "Join",
    "M": QUERY_DIR / DATASET_QUERY / "Mixed",
}

RESULTS_BASE_DIR = RESULTS_DIR / "player_query_awareness_trend"
SNAPSHOT_DIR = RESULTS_BASE_DIR / "snapshot"

_ENTITY_SUFFIX_RE = re.compile(r"\b(jr\.?|sr\.?|iii|iv|ii)\b\.?", re.IGNORECASE)
_NAME_LIKE_COLUMNS = {"name", "player_name", "team_name", "city_name", "owner_name"}


def _strip_diacritics(s: str) -> str:
    """Remove diacritical marks and replace mojibake '?' placeholders."""
    nfkd = unicodedata.normalize("NFKD", s)
    stripped = "".join(c for c in nfkd if not unicodedata.combining(c))
    return stripped.replace("?", "")


def _canon_token(tok: str) -> str:
    """Aggressively normalize a single token for fuzzy comparison."""
    t = tok.strip().lower()
    t = t.replace('"', "").replace("'", "")
    t = _strip_diacritics(t)
    return t


def _tokenize_name(s: str) -> List[str]:
    """Split a normalized name into canonicalized non-empty tokens."""
    return [_canon_token(t) for t in s.lower().split() if _canon_token(t)]


def _fuzzy_align_name_keys(
    gold_df: "pd.DataFrame",
    pred_df: "pd.DataFrame",
    key_cols: List[str],
) -> "pd.DataFrame":
    """
    Rewrite pred key columns so that near-matching names are canonicalized
    to the ground-truth spelling before the RowMatcher sees them.

    Matching cascade (applied per name-like key column):
      1. Exact normalized match (identity — no rewrite needed)
      2. Canon-token exact match (diacritics/quotes stripped)
      3. First + last canon-token match
      4. Last-canon-token match with >=1 other shared token
      5. >=2 shared canon-tokens overall
    """
    pred_out = pred_df.copy()
    for col in key_cols:
        if col.lower().replace("_", "") not in {
            c.replace("_", "") for c in _NAME_LIKE_COLUMNS
        }:
            continue
        if col not in gold_df.columns or col not in pred_out.columns:
            continue

        gt_vals = gold_df[col].dropna().unique().tolist()
        gt_lookup: Dict[str, str] = {}
        gt_canon_lookup: Dict[str, str] = {}
        gt_first_last: Dict[Tuple[str, str], str] = {}
        gt_by_last: Dict[str, List[str]] = {}
        gt_token_sets: Dict[str, set] = {}

        for gv in gt_vals:
            gs = str(gv).strip()
            gn = gs
            gt_lookup[gn] = gn
            canon_full = _strip_diacritics(gn.replace('"', "").replace("'", "").replace("?", ""))
            gt_canon_lookup[" ".join(canon_full.lower().split())] = gn
            toks = _tokenize_name(gn)
            gt_token_sets[gn] = set(toks)
            if len(toks) >= 2:
                fl = (toks[0], toks[-1])
                gt_first_last.setdefault(fl, gn)
                gt_by_last.setdefault(toks[-1], []).append(gn)
            elif toks:
                gt_by_last.setdefault(toks[0], []).append(gn)

        def _best_gt(pred_name: str) -> str:
            pn = str(pred_name).strip()
            if pn in gt_lookup:
                return pn

            canon_pn = _strip_diacritics(pn.replace('"', "").replace("'", "").replace("?", ""))
            canon_pn = " ".join(canon_pn.lower().split())
            if canon_pn in gt_canon_lookup:
                return gt_canon_lookup[canon_pn]

            ptoks = _tokenize_name(pn)
            if not ptoks:
                return pn

            if len(ptoks) >= 2:
                fl = (ptoks[0], ptoks[-1])
                if fl in gt_first_last:
                    return gt_first_last[fl]

            last = ptoks[-1]
            pset = set(ptoks)
            if last in gt_by_last:
                for candidate in gt_by_last[last]:
                    shared = pset & gt_token_sets[candidate]
                    if len(shared) >= 2:
                        return candidate

            for gn, gset in gt_token_sets.items():
                if len(pset & gset) >= 2:
                    return gn

            if len(ptoks) >= 2 and last in gt_by_last:
                pfirst = ptoks[0]
                for candidate in gt_by_last[last]:
                    ctoks = sorted(gt_token_sets[candidate])
                    for ct in ctoks:
                        if ct.startswith(pfirst) and len(pfirst) >= 2:
                            return candidate

            return pn

        pred_out[col] = pred_out[col].apply(
            lambda v: _best_gt(v) if pd.notna(v) and str(v).strip() else v
        )

    rewritten = (pred_out[key_cols] != pred_df[key_cols]).any(axis=None)
    if rewritten:
        changed = int((pred_out[key_cols] != pred_df[key_cols]).any(axis=1).sum())
        logger.info(f"[FuzzyAlign] Rewrote {changed} pred rows to match GT name spelling")

    return pred_out


@dataclass
class TrendQueryMetrics:
    query_id: str
    query_text: str
    success: bool
    delta_type: str
    latency_s: float
    result_rows: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    macro_f1: Optional[float]        # None for aggregation queries
    macro_precision: Optional[float]  # None for aggregation queries
    macro_recall: Optional[float]     # None for aggregation queries
    gt_result_count: int
    matched_rows: Optional[int]       # None for aggregation queries
    is_agg: bool
    relative_error: Optional[float] = None
    error: Optional[str] = None


class TokenTracker:
    """Tracks LLM token usage across calls in this process."""

    def __init__(self) -> None:
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def snapshot(self) -> Tuple[int, int]:
        return self.prompt_tokens, self.completion_tokens

    def delta(self, before: Tuple[int, int]) -> Tuple[int, int]:
        return self.prompt_tokens - before[0], self.completion_tokens - before[1]

    def add(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.prompt_tokens += max(0, int(prompt_tokens))
        self.completion_tokens += max(0, int(completion_tokens))


def _approx_tokens(text: Optional[str]) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / 4))


def patch_ollama_for_token_tracking(token_tracker: TokenTracker) -> None:
    """
    Monkey-patch OllamaClient.generate for per-query token tracking.
    Uses conservative token estimation from prompt/response text length.
    """
    original_generate = OllamaClient.generate

    def wrapped_generate(self, prompt: str, max_tokens: int = 0, temperature: float = 0.0, system_prompt: Optional[str] = None) -> str:  # noqa: ANN001
        result = original_generate(self, prompt, max_tokens=max_tokens, temperature=temperature, system_prompt=system_prompt)
        p_tok = _approx_tokens(prompt) + _approx_tokens(system_prompt)
        c_tok = _approx_tokens(result)
        token_tracker.add(p_tok, c_tok)
        return result

    OllamaClient.generate = wrapped_generate


def setup_logging(log_file: Path) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    fh = logging.FileHandler(log_file)
    ch = logging.StreamHandler(sys.stdout)
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(fh)
    root.addHandler(ch)


def _norm_key(val: Any) -> str:
    s = " ".join(str(val).strip().lower().split())
    s = _ENTITY_SUFFIX_RE.sub("", s)
    s = re.sub(r"[,\.\(\)]", "", s)
    return " ".join(s.split())


def _normalize_key_cols(df: "pd.DataFrame", key_cols: List[str]) -> "pd.DataFrame":
    out = df.copy()
    for col in key_cols:
        if col in out.columns:
            out[col] = out[col].apply(lambda v: _norm_key(v) if pd.notna(v) else "")
    return out


def _resolve_primary_keys_for_alignment(
    primary_keys: List[str],
    gold_df: "pd.DataFrame",
    pred_df: "pd.DataFrame",
) -> List[str]:
    """
    Resolve evaluator key names against actual DataFrame columns.

    sql_parser may return qualified keys (e.g., "city.state_name"), while
    result DataFrames commonly contain unqualified columns ("state_name").
    """
    gold_cols = {str(c) for c in gold_df.columns}
    pred_cols = {str(c) for c in pred_df.columns}

    resolved: List[str] = []
    for key in primary_keys:
        candidates = [
            key,
            key.split(".")[-1],
            _std_col(key),
            _std_col(key.split(".")[-1]),
        ]
        chosen = next((c for c in candidates if c in gold_cols and c in pred_cols), None)
        if chosen and chosen not in resolved:
            resolved.append(chosen)

    return resolved or primary_keys


def _augment_sql_with_entity(sql: str, entity_col: str, dialect: str = "duckdb") -> Optional[str]:
    try:
        parsed = sqlglot.parse_one(sql, error_level="ignore")
    except Exception:
        return None
    if parsed.find(_sqlglot_exp.Star):
        return None
    if parsed.args.get("group"):
        return None
    existing = {
        c.name.lower()
        for c in parsed.find_all(_sqlglot_exp.Column)
        if isinstance(c.parent, _sqlglot_exp.Select)
    }
    if entity_col.lower() in existing:
        return None
    parsed = parsed.select(_sqlglot_exp.column(entity_col))
    return parsed.sql(dialect=dialect)


def _fetch_quwarts_with_entity(quwarts_db: Path, sql: str, entity_col: str) -> Optional[List[Dict[str, Any]]]:
    aug = _augment_sql_with_entity(sql, entity_col, dialect="sqlite")
    if aug is None:
        return None
    try:
        con = sqlite3.connect(str(quwarts_db))
        con.row_factory = sqlite3.Row
        cur = con.execute(aug)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, row)) for row in cur.fetchall()]
        con.close()
        return rows
    except Exception as exc:
        logger.warning(f"[Eval] Augmented QuWARTS query failed: {exc}")
        return None


def _build_pred_df(
    quwarts_rows: List[Dict[str, Any]],
    expected_columns: List[str],
    stop_columns: List[str],
    attributes: Dict[str, Any],
) -> "pd.DataFrame":
    df = pd.DataFrame(quwarts_rows) if quwarts_rows else pd.DataFrame(columns=expected_columns)
    df = _drop_unnamed(df)
    df = df.rename(columns={c: _std_col(c) for c in df.columns})
    df = _norm_file_cols(df)
    df = _add_missing_cols(df, expected_columns)
    df = _add_missing_cols(df, stop_columns)
    df = _clean_string_cols(df)
    df = _norm_types(df, attributes)
    return df


def _safe_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if not s:
        return None
    try:
        out = float(s)
    except Exception:
        return None
    if not math.isfinite(out):
        return None
    return out


def _cell_relative_error(pred: Any, gold: Any) -> float:
    p = _safe_float(pred)
    g = _safe_float(gold)
    if p is None and g is None:
        return 0.0
    if p is None or g is None:
        return 1.0
    if abs(g) < 1e-12:
        return 0.0 if abs(p) < 1e-12 else abs(p - g)
    return abs(p - g) / abs(g)


def _agg_row_key(row: Dict[str, Any], key_cols: List[str]) -> Tuple[str, ...]:
    return tuple(
        "" if c not in row or row[c] is None else str(row[c]).strip().lower()
        for c in key_cols
    )


def _compute_aggregation_relative_error(
    parsed_sql: Any,
    pred_rows: List[Dict[str, Any]],
    gold_rows: List[Dict[str, Any]],
) -> Optional[float]:
    """Mean relative error across all aggregate cells; None when not applicable."""
    if parsed_sql.query_type != "aggregation":
        return None
    agg_cols = [item.output_name for item in parsed_sql.select_items if item.is_agg]
    if not agg_cols:
        return None
    if not gold_rows and not pred_rows:
        return 0.0

    group_cols = [item.output_name for item in parsed_sql.select_items if not item.is_agg]
    errors: List[float] = []

    if not group_cols:
        gold_row = gold_rows[0] if gold_rows else {}
        pred_row = pred_rows[0] if pred_rows else {}
        for c in agg_cols:
            errors.append(_cell_relative_error(pred_row.get(c), gold_row.get(c)))
        extra_rows = abs(len(pred_rows) - len(gold_rows))
        if extra_rows > 0:
            errors.extend([1.0] * (extra_rows * max(1, len(agg_cols))))
        return float(sum(errors) / len(errors)) if errors else None

    pred_map = {_agg_row_key(r, group_cols): r for r in pred_rows}
    gold_map = {_agg_row_key(r, group_cols): r for r in gold_rows}
    for key in set(pred_map.keys()) | set(gold_map.keys()):
        prow = pred_map.get(key)
        grow = gold_map.get(key)
        for c in agg_cols:
            if prow is None or grow is None:
                errors.append(1.0)
            else:
                errors.append(_cell_relative_error(prow.get(c), grow.get(c)))

    return float(sum(errors) / len(errors)) if errors else None


def evaluate_with_official_framework(
    sql: str,
    quwarts_rows: List[Dict[str, Any]],
    *,
    gt_runner: "_GtRunner",
    sql_parser: "_SqlParser",
    row_matcher: "_RowMatcher",
    settings: "_EvalSettings",
    attributes: Dict[str, Any],
    identity_col: Optional[str],
    phase2_db: Path,
    output_dir: Path,
) -> Dict[str, Any]:
    parsed = sql_parser.parse(sql)
    is_agg = parsed.query_type == "aggregation"

    # ── Aggregation queries: relative error is the correct metric; F1 is not ──
    # F1/precision/recall is a set-membership metric for checking whether the
    # right *entities* are returned.  For aggregations (COUNT, SUM, AVG …) what
    # matters is how close the numeric answers are, which relative error captures.
    # We skip the row-matcher entirely for agg queries and return macro_f1=None.
    if is_agg:
        gold_df = gt_runner.run(sql)
        relative_error: Optional[float] = None
        try:
            relative_error = _compute_aggregation_relative_error(
                parsed,
                quwarts_rows,
                gold_df.to_dict(orient="records"),
            )
        except Exception as re_exc:
            logger.warning(f"[Eval] Relative error computation failed ({re_exc}); skipping.")
        return {
            "macro_f1": None,
            "macro_precision": None,
            "macro_recall": None,
            "is_agg": True,
            "gt_result_count": len(gold_df),
            "matched_rows": None,
            "relative_error": relative_error,
        }

    # ── Non-aggregation queries: row-matcher + F1 ────────────────────────────
    entity = identity_col or "name"
    aug_gt = _augment_sql_with_entity(sql, entity, dialect="duckdb")
    gt_sql = aug_gt if aug_gt else sql
    quwarts_cols = {k.lower() for k in (quwarts_rows[0].keys() if quwarts_rows else {})}
    if entity.lower() not in quwarts_cols and phase2_db.exists():
        aug_quwarts = _fetch_quwarts_with_entity(phase2_db, sql, entity)
        effective_quwarts = aug_quwarts if aug_quwarts is not None else quwarts_rows
    else:
        effective_quwarts = quwarts_rows

    gold_df = gt_runner.run(gt_sql)
    primary_keys: List[str] = [entity] if entity in gold_df.columns else parsed.primary_keys

    manifest_for_pred = _QueryManifest(gt_sql, sql_parser.parse(gt_sql), attributes)
    pred_df = _build_pred_df(
        effective_quwarts,
        expected_columns=list(gold_df.columns),
        stop_columns=manifest_for_pred.stop_columns,
        attributes=attributes,
    )

    primary_keys = _resolve_primary_keys_for_alignment(primary_keys, gold_df, pred_df)

    gold_norm = _normalize_key_cols(gold_df, primary_keys)
    pred_norm = _normalize_key_cols(pred_df, primary_keys)

    pred_norm = _fuzzy_align_name_keys(gold_norm, pred_norm, primary_keys)

    try:
        match_result = row_matcher.match(
            gold_df=gold_norm,
            pred_df=pred_norm,
            primary_keys=primary_keys,
            attr_descriptions=attributes,
            query_type=parsed.query_type,
        )
    except KeyError as ke:
        logger.warning(f"[Eval] RowMatcher key error ({ke}) — returning zero metrics")
        return {
            "macro_f1": 0.0,
            "macro_precision": 0.0,
            "macro_recall": 0.0,
            "is_agg": False,
            "gt_result_count": len(gold_df),
            "matched_rows": 0,
            "relative_error": None,
        }

    calc = _MetricCalculator(manifest_for_pred, settings)
    row_metrics = calc.compute(match_result)
    macro_f1 = row_metrics.get("macro_f1", 0.0)
    macro_precision = row_metrics.get("macro_precision", 0.0)
    macro_recall = row_metrics.get("macro_recall", 0.0)
    if not math.isfinite(macro_f1):
        macro_f1 = 0.0
    if not math.isfinite(macro_precision):
        macro_precision = 0.0
    if not math.isfinite(macro_recall):
        macro_recall = 0.0

    try:
        writer = _ResultWriter(output_dir=output_dir)
        writer.write(gold_df, match_result.gold_aligned, match_result.pred_aligned, row_metrics)
    except Exception as we:
        logger.warning(f"[Eval] Could not write per-query outputs: {we}")

    return {
        "macro_f1": macro_f1,
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "is_agg": False,
        "gt_result_count": len(gold_df),
        "matched_rows": match_result.matched_rows,
        "relative_error": None,
    }


def collect_training_workload(dataset_query: str) -> List[str]:
    """Collect all training queries used to restore lattice state."""
    all_queries: List[str] = []
    base = QUERY_DIR / dataset_query

    def _load(path: Path) -> None:
        if not path.exists():
            return
        txt = path.read_text()
        parts = re.split(r"-- (?:Inspiration: )?Query ", txt)
        for part in parts[1:]:
            lines = part.strip().split("\n")
            if not lines:
                continue
            sql_text = "\n".join(lines[1:]).strip()
            while sql_text and sql_text.split("\n")[0].strip().startswith("--"):
                sql_text = "\n".join(sql_text.split("\n")[1:]).strip()
            if sql_text:
                all_queries.append(sql_text)

    _load(base / "Agg" / "agg_queries.sql")
    for query_type in ["Filter", "Select", "Mixed"]:
        type_dir = base / query_type
        if type_dir.exists():
            for sql_file in sorted(type_dir.glob("*.sql")):
                _load(sql_file)
    _load(base / "Join" / "join_queries.sql")
    return all_queries


def parse_trend_queries(sql_file: Path) -> List[Tuple[str, str]]:
    """Parse Q1..Q10 from query_aware_trend_queries.sql."""
    if not sql_file.exists():
        raise FileNotFoundError(f"Trend SQL file not found: {sql_file}")
    lines = sql_file.read_text().splitlines()
    queries: List[Tuple[str, str]] = []

    i = 0
    while i < len(lines):
        m = re.match(r"\s*--\s*Q(\d+)\s*:", lines[i], flags=re.IGNORECASE)
        if not m:
            i += 1
            continue
        qid = f"Q{int(m.group(1))}"
        i += 1
        sql_lines: List[str] = []
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if re.match(r"\s*--\s*Q\d+\s*:", raw, flags=re.IGNORECASE):
                break
            if s.startswith("--") or s == "":
                i += 1
                continue
            sql_lines.append(raw)
            if ";" in raw:
                i += 1
                break
            i += 1

        sql = "\n".join(sql_lines).strip()
        if sql and not sql.endswith(";"):
            sql += ";"
        if sql:
            queries.append((qid, sql))

    queries.sort(key=lambda x: int(x[0][1:]))
    return queries


def parse_category_queries(sql_file: Path, prefix: str, start_idx: int) -> List[Tuple[str, str]]:
    """
    Parse SQL statements from a category SQL file and assign IDs like S1, F7, etc.
    """
    if not sql_file.exists():
        return []
    text = sql_file.read_text()
    lines = text.splitlines()
    i = 0
    idx = start_idx
    queries: List[Tuple[str, str]] = []

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if s.startswith("--") or s == "":
            i += 1
            continue

        query_id = f"{prefix}{idx}"
        idx += 1
        sql_lines: List[str] = []
        while i < len(lines):
            raw = lines[i]
            s = raw.strip()
            if not sql_lines and (s.startswith("--") or s == ""):
                i += 1
                continue
            sql_lines.append(raw)
            if ";" in raw:
                i += 1
                break
            i += 1

        sql = "\n".join(sql_lines).strip().rstrip(";").strip()
        if sql:
            queries.append((query_id, sql))

    return queries


def parse_all_category_queries() -> List[Tuple[str, str]]:
    """Parse all SQL queries from Select/Filter/Agg/Join/Mixed folders."""
    all_queries: List[Tuple[str, str]] = []
    for prefix in ["S", "F", "A", "J", "M"]:
        category_dir = QUERY_CATEGORY_DIRS[prefix]
        if not category_dir.exists():
            logger.warning(f"Missing query category directory: {category_dir}")
            continue
        sql_files = sorted(category_dir.glob("*.sql"))
        if not sql_files:
            logger.warning(f"No SQL files found in category directory: {category_dir}")
            continue

        next_idx = 1
        for sql_file in sql_files:
            parsed = parse_category_queries(sql_file, prefix, next_idx)
            if parsed:
                all_queries.extend(parsed)
                next_idx += len(parsed)

    logger.info(f"Loaded {len(all_queries)} category queries from query folders")
    return all_queries


def load_redd_enabled_query_ids() -> Set[str]:
    """
    Load active (uncommented) query IDs from ReDD trend script NL_QUERY_SPECS.
    """
    if not REDD_TREND_FILE.exists():
        raise FileNotFoundError(f"ReDD trend file not found: {REDD_TREND_FILE}")

    # Import directly from file path to avoid package/module name conflicts.
    import importlib.util
    import sys

    module_name = "_quwarts_redd_trend_module"
    # If already loaded, reuse to avoid re-executing dataclass decorators
    if module_name in sys.modules:
        module = sys.modules[module_name]
    else:
        spec = importlib.util.spec_from_file_location(module_name, REDD_TREND_FILE)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load module spec from: {REDD_TREND_FILE}")
        module = importlib.util.module_from_spec(spec)
        # CRITICAL: Register in sys.modules BEFORE exec_module so that
        # @dataclass decorators can resolve ForwardRef/Optional types correctly.
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

    nl_specs = getattr(module, "NL_QUERY_SPECS", None)
    if not isinstance(nl_specs, dict) or not nl_specs:
        raise RuntimeError("NL_QUERY_SPECS missing or empty in ReDD trend file")
    return set(str(k) for k in nl_specs.keys())


def _save_rows_csv(rows: List[Dict[str, Any]], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        with out_csv.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["_empty"])
        return
    cols: List[str] = []
    for r in rows:
        for k in r.keys():
            if k not in cols:
                cols.append(k)
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def _first_existing(paths: List[Path]) -> Optional[Path]:
    for p in paths:
        if p.exists():
            return p
    return None


def verify_snapshot_integrity(snapshot_db: Path, snapshot_cache: Path) -> None:
    """
    Hard pre-flight checks run before any query execution.

    Raises RuntimeError immediately if any condition is violated.  The goal is
    to surface setup problems (missing files, stale index, incomplete extraction)
    before the first LLM call so the user gets a clear error message rather than
    thousands of spurious chunk extractions or silent wrong results.

    Checks performed:
      1. Snapshot DB is a readable SQLite file.
      2. Attribute index file exists at the expected path inside snapshot_cache.
      3. Attribute index is not stale — at least some of its chunk IDs exist in
         the DB's candidate_index table (a fully empty intersection means the
         index was built from a different preprocessing run than the DB).
      4. Metadata registry is complete — every table has STATUS_FULL for all its
         columns (incomplete extraction means test queries will trigger row delta
         unnecessarily, or return wrong results).
      5. Every table referenced in the training workload has at least one
         candidate chunk in the DB.
    """
    errors: List[str] = []

    # ── 1. Snapshot DB is a valid SQLite file ────────────────────────────────
    if not snapshot_db.exists():
        raise RuntimeError(
            f"Snapshot DB not found: {snapshot_db}\n"
            f"Run preprocessing first (test_player_workload.py)."
        )
    try:
        con = sqlite3.connect(str(snapshot_db))
        con.execute("SELECT 1")
        con.close()
    except Exception as exc:
        raise RuntimeError(
            f"Snapshot DB is not a valid SQLite file ({snapshot_db}): {exc}"
        ) from exc

    # ── 2. Attribute index file exists ───────────────────────────────────────
    attr_index_path = snapshot_cache / DATASET / "attribute_index.json"
    if not attr_index_path.exists():
        raise RuntimeError(
            f"Attribute index not found: {attr_index_path}\n"
            f"Re-run preprocessing to rebuild it (test_player_workload.py)."
        )

    # Open DB once for the remaining checks.
    con = sqlite3.connect(str(snapshot_db))
    con.row_factory = sqlite3.Row

    try:
        # ── 3. Attribute index is not stale ──────────────────────────────────
        try:
            attr_data = json.loads(attr_index_path.read_text())
            # Collect all chunk IDs the index knows about.
            index_chunk_ids: Set[str] = set()
            for _table, entries in attr_data.get("attr_to_chunks", {}).items():
                for _attr, entry in entries.items():
                    index_chunk_ids.update(entry.get("chunk_ids", []))

            if index_chunk_ids:
                placeholders = ",".join("?" * min(len(index_chunk_ids), 500))
                sample = list(index_chunk_ids)[:500]
                rows = con.execute(
                    f"SELECT COUNT(*) FROM candidate_index WHERE chunk_id IN ({placeholders})",
                    sample,
                ).fetchone()
                overlap = rows[0] if rows else 0
                if overlap == 0:
                    errors.append(
                        f"Attribute index is STALE: none of its {len(index_chunk_ids)} "
                        f"chunk ID(s) exist in candidate_index. The index was built from "
                        f"a different preprocessing run than the snapshot DB. "
                        f"Re-run preprocessing and refresh the snapshot "
                        f"(--refresh-snapshot)."
                    )
        except Exception as exc:
            errors.append(f"Could not validate attribute index freshness: {exc}")

        # ── 4. Metadata registry is complete (all columns STATUS_FULL) ───────
        try:
            incomplete = con.execute(
                "SELECT table_name, column_name, status "
                "FROM metadata_registry "
                "WHERE status != 'FULL' "
                "ORDER BY table_name, column_name"
            ).fetchall()
            if incomplete:
                detail = ", ".join(
                    f"{r['table_name']}.{r['column_name']}={r['status']}"
                    for r in incomplete[:10]
                )
                if len(incomplete) > 10:
                    detail += f" … (+{len(incomplete) - 10} more)"
                errors.append(
                    f"Metadata registry has {len(incomplete)} column(s) that are not "
                    f"STATUS_FULL — preprocessing may not have completed successfully: "
                    f"{detail}. Re-run preprocessing."
                )
        except Exception as exc:
            errors.append(f"Could not query metadata_registry: {exc}")

        # ── 5. Every table has at least one candidate chunk ──────────────────
        try:
            counts = {
                r["table_name"]: r["cnt"]
                for r in con.execute(
                    "SELECT table_name, COUNT(*) AS cnt FROM candidate_index GROUP BY table_name"
                ).fetchall()
            }
            for table in ["player", "team", "city", "owner"]:
                if counts.get(table, 0) == 0:
                    errors.append(
                        f"Table '{table}' has 0 candidate chunks in candidate_index — "
                        f"the sieve/ingestion step may have failed for this table."
                    )
        except Exception as exc:
            errors.append(f"Could not query candidate_index: {exc}")

    finally:
        con.close()

    if errors:
        bullet_list = "\n".join(f"  • {e}" for e in errors)
        raise RuntimeError(
            f"Snapshot integrity check failed ({len(errors)} issue(s)):\n{bullet_list}"
        )

    logger.info(
        "[PreFlight] Snapshot integrity OK — DB, attribute index, metadata registry, "
        "and candidate chunks all verified."
    )


def ensure_snapshot_artifacts(refresh_snapshot: bool = False) -> Tuple[Path, Optional[Path]]:
    """
    Ensure snapshot copies exist for:
    - DB file
    - cache directory
    - extraction cache directory
    Returns (snapshot_db_path, snapshot_identity_columns_path_or_none)
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    # Prefer latest timestamped preprocessing run, then legacy paths.
    preprocess_base = RESULTS_DIR / "player_workload_preprocess"
    latest_run = None
    if preprocess_base.exists():
        runs = sorted(preprocess_base.glob("run_*"), key=lambda p: p.name, reverse=True)
        for run_dir in runs:
            candidate = run_dir / "Player_preprocessed.db"
            if candidate.exists():
                latest_run = candidate
                break
    source_db_candidates = [
        latest_run,
        RESULTS_DIR / "player_workload_test" / "checkpoint" / "Player_preprocessed.db",
        Path(__file__).parent / "quwarts-2.db",
        DB_DIR / "quwarts.db",
        Path(__file__).parent / "quwarts-owner-only.db",
    ]
    source_db = _first_existing([p for p in source_db_candidates if p is not None])
    if source_db is None:
        raise FileNotFoundError(
            "No source DB found. Checked: "
            + ", ".join(str(p) for p in source_db_candidates)
        )

    # When using a timestamped run, cache lives in that run's .cache
    source_run_dir = source_db.parent if source_db == latest_run else None
    source_cache = source_run_dir / ".cache" if source_run_dir else CACHE_DIR
    source_extractions = source_cache / "extractions"

    # The DB, cache, and extractions snapshot must all come from the SAME
    # preprocessing run.  --refresh-snapshot therefore refreshes all three
    # atomically, not just the DB.  A stale cache paired with a fresh DB
    # causes the attribute index chunk IDs to diverge from the candidate_index
    # in the DB, which triggers the pre-flight integrity check failure.
    snapshot_db = SNAPSHOT_DIR / "player_snapshot.db"
    snapshot_cache = SNAPSHOT_DIR / "cache_snapshot"
    snapshot_extractions = SNAPSHOT_DIR / "extractions_snapshot"

    if refresh_snapshot:
        for artifact in (snapshot_db, snapshot_cache, snapshot_extractions):
            if artifact.exists():
                if artifact.is_dir():
                    shutil.rmtree(artifact)
                else:
                    artifact.unlink()
                logger.info(f"Removed existing snapshot artifact (refresh): {artifact}")

    if snapshot_db.exists():
        logger.info(f"Snapshot DB already exists: {snapshot_db}")
    else:
        shutil.copy2(source_db, snapshot_db)
        logger.info(f"Created snapshot DB: {snapshot_db} (from {source_db})")

    if snapshot_cache.exists():
        logger.info(f"Snapshot cache already exists: {snapshot_cache}")
    elif source_cache.exists():
        shutil.copytree(source_cache, snapshot_cache)
        logger.info(f"Created snapshot cache: {snapshot_cache}")
    else:
        logger.warning(f"Cache dir not found, skipping copy: {source_cache}")

    if snapshot_extractions.exists():
        logger.info(f"Snapshot extraction cache already exists: {snapshot_extractions}")
    elif source_extractions.exists():
        shutil.copytree(source_extractions, snapshot_extractions)
        logger.info(f"Created snapshot extraction cache: {snapshot_extractions}")
    else:
        logger.warning(f"Extraction cache dir not found, skipping copy: {source_extractions}")

    identity_candidates = [
        (source_run_dir / "Player_identity_columns.json") if source_run_dir else None,
        RESULTS_DIR / "player_workload_test" / "checkpoint" / "Player_identity_columns.json",
        RESULTS_DIR / "player_workload_test" / "checkpoint" / "player_identity_columns.json",
    ]
    source_identity = _first_existing([p for p in identity_candidates if p is not None])
    snapshot_identity = SNAPSHOT_DIR / "Player_identity_columns.json"
    if source_identity and not snapshot_identity.exists():
        shutil.copy2(source_identity, snapshot_identity)
        logger.info(f"Created snapshot identity file: {snapshot_identity}")
    elif snapshot_identity.exists():
        logger.info(f"Snapshot identity file already exists: {snapshot_identity}")

    return snapshot_db, (snapshot_identity if snapshot_identity.exists() else None)


def _infer_identity_col_for_query(sql: str, identity_columns: Dict[str, str]) -> Optional[str]:
    """
    Pick identity column based on first table in FROM clause.
    Falls back to player/name if unknown.
    """
    try:
        parsed = sqlglot.parse_one(sql, error_level="ignore")
        first_table = None
        for t in parsed.find_all(sqlglot.expressions.Table):
            first_table = t.name
            break
        if first_table:
            if first_table in identity_columns:
                return identity_columns[first_table]
            lc_map = {k.lower(): v for k, v in identity_columns.items()}
            if first_table.lower() in lc_map:
                return lc_map[first_table.lower()]
    except Exception:
        pass
    return identity_columns.get("player", "name")


def _build_run_paths() -> Tuple[Path, Path, Path, Path]:
    run_tag = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RESULTS_BASE_DIR / f"run_{run_tag}"
    query_results_dir = run_dir / "query_results"
    query_tables_dir = run_dir / "query_tables"
    plots_dir = run_dir / "plots"
    return run_dir, query_results_dir, query_tables_dir, plots_dir


def run_trend_queries(
    snapshot_db: Path,
    identity_file: Optional[Path],
    run_dir: Path,
    query_results_dir: Path,
    query_tables_dir: Path,
    plots_dir: Path,
    *,
    projection_fastpath: bool = False,
    projection_fastpath_col_batch_size: int = 0,
) -> List[TrendQueryMetrics]:
    run_dir.mkdir(parents=True, exist_ok=True)
    query_results_dir.mkdir(parents=True, exist_ok=True)
    query_tables_dir.mkdir(parents=True, exist_ok=True)
    plots_dir.mkdir(parents=True, exist_ok=True)

    # ── Pre-flight: fail fast before touching any LLM or copying the DB ──────
    snapshot_cache = SNAPSHOT_DIR / "cache_snapshot"
    if not snapshot_cache.exists():
        raise RuntimeError(
            f"Snapshot cache not found: {snapshot_cache}\n"
            f"Re-run preprocessing (test_player_workload.py) and ensure the "
            f"snapshot was created (or use --refresh-snapshot)."
        )
    verify_snapshot_integrity(snapshot_db, snapshot_cache)
    # ─────────────────────────────────────────────────────────────────────────

    working_db = run_dir / "player_trend_working.db"
    shutil.copy2(snapshot_db, working_db)
    logger.info(f"Working DB copied from snapshot: {working_db}")

    identity_columns: Dict[str, str] = {}
    if identity_file and identity_file.exists():
        identity_columns = json.loads(identity_file.read_text())
        logger.info(f"Loaded identity columns: {identity_columns}")
    else:
        logger.warning("No identity columns file found; fallback identity rules will be used.")

    # IMPORTANT: isolate extraction cache per run so one full trend run cannot
    # warm the next run. Queries inside the same run still share this cache.
    run_cache_root = run_dir / ".cache"
    run_cache_root.mkdir(parents=True, exist_ok=True)
    original_cache_dir = config_module.CACHE_DIR
    config_module.CACHE_DIR = run_cache_root
    logger.info(
        "Using run-isolated extraction cache root: %s (restored after run)",
        run_cache_root,
    )

    token_tracker = TokenTracker()
    patch_ollama_for_token_tracking(token_tracker)

    try:
        runner = QuWARTSRunner(
            dataset=DATASET,
            postgres_uri=f"sqlite:///{working_db}",
            use_projection_fastpath=projection_fastpath,
            projection_fastpath_col_batch_size=projection_fastpath_col_batch_size,
            cache_dir=snapshot_cache,  # Use snapshot cache for attribute index
        )
        training_queries = collect_training_workload(DATASET_QUERY)
        if training_queries:
            runner.restore_lattice(training_queries)
            logger.info(f"Restored lattice with {len(training_queries)} training queries.")
        if identity_columns:
            runner.identity_columns.update(identity_columns)
            runner.delta_engine.identity_columns = runner.identity_columns

        eval_attributes: Dict[str, Any] = _load_json(ATTRIBUTES_FILE) if ATTRIBUTES_FILE.exists() else {}
        eval_settings = _EvalSettings(llm_provider="none")
        eval_gt_runner = _GtRunner(gt_dir=GROUND_TRUTH_DIR, attributes=eval_attributes)
        eval_sql_parser = _SqlParser()
        eval_row_matcher = _RowMatcher(settings=eval_settings)

        # Keep QuWARTS query set aligned with ReDD by running only IDs that are
        # currently uncommented/active in ReDD's NL_QUERY_SPECS.
        redd_enabled_ids = load_redd_enabled_query_ids()
        trend_queries = [
            (qid, sql) for qid, sql in parse_all_category_queries()
            if qid in redd_enabled_ids
        ]
        if not trend_queries:
            raise RuntimeError(
                "No runnable queries after applying ReDD uncommented filter. "
                f"ReDD file: {REDD_TREND_FILE}"
            )
        logger.info(
            "Running %d QuWARTS queries aligned to uncommented ReDD IDs",
            len(trend_queries),
        )

        metrics: List[TrendQueryMetrics] = []
        for query_id, query_text in trend_queries:
            logger.info("=" * 70)
            logger.info(f"Executing {query_id}")
            before = token_tracker.snapshot()
            t0 = time.time()

            try:
                result = runner.execute_query(query_text)
                latency = time.time() - t0
                d_prompt, d_completion = token_tracker.delta(before)
                d_total = d_prompt + d_completion

                out_csv = query_tables_dir / f"{query_id}.csv"
                out_json = query_tables_dir / f"{query_id}.json"
                _save_rows_csv(result.results, out_csv)
                out_json.write_text(json.dumps(result.results, indent=2, default=str))

                eval_out: Dict[str, Any] = {}
                if result.success:
                    eval_out = evaluate_with_official_framework(
                        query_text,
                        result.results,
                        gt_runner=eval_gt_runner,
                        sql_parser=eval_sql_parser,
                        row_matcher=eval_row_matcher,
                        settings=eval_settings,
                        attributes=eval_attributes,
                        identity_col=_infer_identity_col_for_query(query_text, identity_columns),
                        phase2_db=working_db,
                        output_dir=query_results_dir / query_id,
                    )

                item = TrendQueryMetrics(
                    query_id=query_id,
                    query_text=query_text,
                    success=result.success,
                    delta_type=result.delta_type,
                    latency_s=latency,
                    result_rows=len(result.results),
                    prompt_tokens=d_prompt,
                    completion_tokens=d_completion,
                    total_tokens=d_total,
                    macro_f1=eval_out.get("macro_f1"),
                    macro_precision=eval_out.get("macro_precision"),
                    macro_recall=eval_out.get("macro_recall"),
                    gt_result_count=eval_out.get("gt_result_count", 0),
                    matched_rows=eval_out.get("matched_rows"),
                    is_agg=eval_out.get("is_agg", False),
                    relative_error=eval_out.get("relative_error"),
                    error=result.error if not result.success else None,
                )
                metrics.append(item)

                # Augment per-query acc.json with time and token cost (evaluation writes acc.json only)
                acc_path = query_results_dir / query_id / "acc.json"
                if acc_path.exists():
                    try:
                        acc_data = json.loads(acc_path.read_text())
                        acc_data["query_id"] = query_id
                        acc_data["latency_s"] = round(latency, 4)
                        acc_data["prompt_tokens"] = d_prompt
                        acc_data["completion_tokens"] = d_completion
                        acc_data["total_tokens"] = d_total
                        acc_data["result_rows"] = len(result.results)
                        acc_data["relative_error"] = eval_out.get("relative_error")
                        acc_path.write_text(json.dumps(acc_data, indent=2))
                    except Exception as acc_err:
                        logger.warning(f"Could not augment {acc_path} with time/cost: {acc_err}")

                if item.is_agg:
                    rel_err_str = "n/a" if item.relative_error is None else f"{item.relative_error:.4f}"
                    logger.info(
                        f"{query_id}: success={item.success} rows={item.result_rows} "
                        f"latency={item.latency_s:.3f}s tokens={item.total_tokens} "
                        f"RelErr={rel_err_str}"
                    )
                else:
                    logger.info(
                        f"{query_id}: success={item.success} rows={item.result_rows} "
                        f"latency={item.latency_s:.3f}s tokens={item.total_tokens} "
                        f"F1={item.macro_f1:.3f}"
                    )
            except Exception as exc:
                latency = time.time() - t0
                d_prompt, d_completion = token_tracker.delta(before)
                metrics.append(
                    TrendQueryMetrics(
                        query_id=query_id,
                        query_text=query_text,
                        success=False,
                        delta_type="ERROR",
                        latency_s=latency,
                        result_rows=0,
                        prompt_tokens=d_prompt,
                        completion_tokens=d_completion,
                        total_tokens=d_prompt + d_completion,
                        macro_f1=0.0,
                        macro_precision=0.0,
                        macro_recall=0.0,
                        gt_result_count=0,
                        matched_rows=0,
                        is_agg=False,
                        error=str(exc),
                    )
                )
                logger.exception(f"{query_id} failed: {exc}")

        return metrics
    finally:
        config_module.CACHE_DIR = original_cache_dir


def save_metrics(metrics: List[TrendQueryMetrics], run_dir: Path) -> None:
    rows = [asdict(m) for m in metrics]
    out_json = run_dir / "trend_metrics.json"
    out_csv = run_dir / "trend_metrics.csv"
    out_json.write_text(json.dumps(rows, indent=2))
    with out_csv.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        if rows:
            writer.writeheader()
            writer.writerows(rows)
    logger.info(f"Saved metrics JSON: {out_json}")
    logger.info(f"Saved metrics CSV:  {out_csv}")


def plot_metrics(metrics: List[TrendQueryMetrics], plots_dir: Path) -> None:
    if not MATPLOTLIB_AVAILABLE:
        logger.warning("matplotlib not available - skipping plot generation")
        return
    if not metrics:
        logger.warning("No metrics to plot.")
        return

    ordered = sorted(metrics, key=lambda m: int(m.query_id[1:]))
    x_labels = [m.query_id for m in ordered]
    x = list(range(len(x_labels)))

    result_rows = [m.result_rows for m in ordered]
    token_cost = [m.total_tokens for m in ordered]
    latency = [m.latency_s for m in ordered]
    # None for agg queries — plot as NaN so matplotlib leaves a gap
    import math as _math
    f1 = [m.macro_f1 if m.macro_f1 is not None else float("nan") for m in ordered]
    rel_err = [m.relative_error if m.relative_error is not None else float("nan") for m in ordered]

    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle("Player Query-Awareness Trend (Q1..Q10)", fontsize=16, fontweight="bold")

    axes[0, 0].plot(x, result_rows, marker="o", color="#7f8c8d")
    axes[0, 0].set_title("Result Table Size (rows)")
    axes[0, 0].set_xticks(x)
    axes[0, 0].set_xticklabels(x_labels)
    axes[0, 0].set_ylabel("rows")
    axes[0, 0].grid(alpha=0.3)

    axes[0, 1].plot(x, token_cost, marker="o", color="#8e44ad")
    axes[0, 1].set_title("Token Cost (estimated total tokens)")
    axes[0, 1].set_xticks(x)
    axes[0, 1].set_xticklabels(x_labels)
    axes[0, 1].set_ylabel("tokens")
    axes[0, 1].grid(alpha=0.3)

    axes[1, 0].plot(x, latency, marker="o", color="#2980b9")
    axes[1, 0].set_title("Latency")
    axes[1, 0].set_xticks(x)
    axes[1, 0].set_xticklabels(x_labels)
    axes[1, 0].set_ylabel("seconds")
    axes[1, 0].grid(alpha=0.3)

    # Bottom-right: F1 for non-agg, relative error for agg (separate lines)
    non_agg_x = [i for i, m in enumerate(ordered) if not m.is_agg]
    non_agg_f1 = [f1[i] for i in non_agg_x]
    agg_x = [i for i, m in enumerate(ordered) if m.is_agg]
    agg_re = [rel_err[i] for i in agg_x]
    if non_agg_x:
        axes[1, 1].plot(non_agg_x, non_agg_f1, marker="o", color="#27ae60", label="Macro F1 (non-agg)")
    if agg_x:
        axes[1, 1].plot(agg_x, agg_re, marker="s", color="#e67e22", label="Rel. Error (agg, lower=better)")
    axes[1, 1].set_title("Accuracy by Query Type")
    axes[1, 1].set_xticks(x)
    axes[1, 1].set_xticklabels(x_labels)
    axes[1, 1].set_ylabel("score")
    axes[1, 1].grid(alpha=0.3)
    axes[1, 1].legend(fontsize=8)

    plt.tight_layout()
    summary_plot = plots_dir / "query_awareness_trend_summary.png"
    plt.savefig(summary_plot, dpi=300, bbox_inches="tight")
    plt.close(fig)
    logger.info(f"Saved trend summary plot: {summary_plot}")

    # Separate detailed F1/P/R plot (non-agg only)
    p = [m.macro_precision if m.macro_precision is not None else float("nan") for m in ordered]
    r = [m.macro_recall if m.macro_recall is not None else float("nan") for m in ordered]
    fig2, ax2 = plt.subplots(figsize=(12, 5))
    ax2.plot(x, p, marker="o", label="Precision")
    ax2.plot(x, r, marker="o", label="Recall")
    ax2.plot(x, f1, marker="o", label="F1")
    ax2.set_xticks(x)
    ax2.set_xticklabels(x_labels)
    ax2.set_ylim(0.0, 1.0)
    ax2.set_title("Macro Precision/Recall/F1 by Query (non-aggregation queries only)")
    ax2.set_ylabel("score")
    ax2.grid(alpha=0.3)
    ax2.legend()
    plt.tight_layout()
    prf_plot = plots_dir / "query_awareness_trend_prf.png"
    plt.savefig(prf_plot, dpi=300, bbox_inches="tight")
    plt.close(fig2)
    logger.info(f"Saved trend PRF plot: {prf_plot}")


def main() -> int:
    ensure_precise_tokenizer_ready()

    RESULTS_BASE_DIR.mkdir(parents=True, exist_ok=True)
    setup_logging(RESULTS_BASE_DIR / "query_awareness_trend.log")
    run_dir, query_results_dir, query_tables_dir, plots_dir = _build_run_paths()
    ap = argparse.ArgumentParser(description="Run Player query-awareness trend test")
    ap.add_argument(
        "--refresh-snapshot",
        action="store_true",
        help="Recreate snapshot DB from preferred source before running",
    )
    ap.add_argument(
        "--projection-fastpath",
        action="store_true",
        help="Enable projection fast path in QuWARTS runner.",
    )
    ap.add_argument(
        "--projection-fastpath-col-batch-size",
        type=int,
        default=0,
        help="Column batch size for projection fast path (0 = default behavior).",
    )
    args = ap.parse_args()

    logger.info("Starting Player query-awareness trend test...")
    logger.info(f"Trend query source: {TREND_SQL_FILE}")
    logger.info(f"Run output dir: {run_dir}")
    logger.info(
        "Projection fast path: %s (col_batch_size=%s)",
        args.projection_fastpath,
        args.projection_fastpath_col_batch_size,
    )

    try:
        snapshot_db, identity_file = ensure_snapshot_artifacts(refresh_snapshot=args.refresh_snapshot)
        metrics = run_trend_queries(
            snapshot_db,
            identity_file,
            run_dir,
            query_results_dir,
            query_tables_dir,
            plots_dir,
            projection_fastpath=args.projection_fastpath,
            projection_fastpath_col_batch_size=args.projection_fastpath_col_batch_size,
        )
        save_metrics(metrics, run_dir)
        plot_metrics(metrics, plots_dir)

        success_count = sum(1 for m in metrics if m.success)
        non_agg = [m for m in metrics if not m.is_agg]
        avg_f1 = (
            sum(m.macro_f1 for m in non_agg if m.macro_f1 is not None) / len(non_agg)
            if non_agg else 0.0
        )
        agg_metrics = [m for m in metrics if m.is_agg and m.relative_error is not None]
        avg_rel_err = (
            sum(m.relative_error for m in agg_metrics) / len(agg_metrics)
            if agg_metrics else None
        )
        logger.info("=" * 80)
        logger.info(
            f"Completed: {success_count}/{len(metrics)} queries succeeded"
        )
        if non_agg:
            logger.info(
                f"Non-aggregation queries ({len(non_agg)}): avg macro F1={avg_f1:.3f}"
            )
        if avg_rel_err is not None:
            logger.info(
                f"Aggregation queries ({len(agg_metrics)}): avg relative error={avg_rel_err:.4f}"
            )
        logger.info(f"Outputs under: {run_dir}")
        logger.info("=" * 80)

        # Token cost report (Qwen2.5-7B-Instruct tokenizer)
        token_summary = GLOBAL_COUNTER.summary_str()
        logger.info(token_summary)
        token_json_path = run_dir / "token_cost.json"
        GLOBAL_COUNTER.save_json(token_json_path)
        logger.info(f"Token cost JSON saved to: {token_json_path}")

        return 0
    except Exception as exc:
        logger.exception(f"Trend test failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
