"""
Player workload preprocessing for WDIRS.

Runs offline relational synthesis with the Player training workload
(Agg, Filter, Select, Mixed, Join). All outputs are written to a
timestamped run directory so previous runs are never overwritten.

Outputs (per run):
  results/player_workload_preprocess/run_YYYYMMDD_HHMMSS/
    preprocess.log
    wdirs.db
    Player_preprocessed.db   (copy of wdirs.db)
    Player_identity_columns.json
    Player_preprocessing_stats.json
    token_cost.json
    .cache/                  (extractions, entity resolution, etc.)
"""

import json
import logging
import re
import sys
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple

# Token counter must be imported before any WDIRS component.
sys.path.insert(0, str(Path(__file__).parent))
from token_counter import GLOBAL_COUNTER, ensure_precise_tokenizer_ready

sys.path.insert(0, str(Path(__file__).parent))

from wdirs_runner import WDIRSRunner
from config import QUERY_DIR, SOURCE_DATA_DIR, RESULTS_DIR, PROJECT_ROOT

logger = logging.getLogger(__name__)

DATASET = "Player"
DATASET_QUERY = "Player"
TRAINING_QUERY_TYPES = ["Agg", "Filter", "Select", "Mixed", "Join"]
RUN_BASE_DIR = RESULTS_DIR / "player_workload_preprocess"


def setup_logging(log_file: Path) -> None:
    """Configure logging to file and console."""
    log_file.parent.mkdir(parents=True, exist_ok=True)
    handler_file = logging.FileHandler(log_file)
    handler_console = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler_file.setFormatter(formatter)
    handler_console.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    for h in list(root_logger.handlers):
        root_logger.removeHandler(h)
    root_logger.addHandler(handler_file)
    root_logger.addHandler(handler_console)


def load_sql_queries(sql_file: Path) -> List[Tuple[str, str]]:
    """Parse SQL file and return list of (query_id, query_text) tuples.

    Supports both:
      1) Annotated format with '-- Query N:' headers.
      2) Plain SQL format with semicolon-terminated statements.
    """
    queries: List[Tuple[str, str]] = []
    try:
        content = sql_file.read_text()
    except Exception as e:
        logger.warning(f"Could not read {sql_file}: {e}")
        return queries

    # Format 1: '-- Query N:' style.
    parts = re.split(r"-- (?:Inspiration: )?Query ", content)
    if len(parts) > 1:
        for part in parts[1:]:
            lines = part.strip().split("\n")
            if not lines:
                continue
            query_id_line = lines[0]
            try:
                query_id = query_id_line.split(":")[0].split("(")[0].strip()
            except Exception:
                continue
            if not query_id or not query_id[0].isdigit():
                continue
            sql_text = "\n".join(lines[1:]).strip()
            while sql_text and sql_text.split("\n")[0].strip().startswith("--"):
                sql_text = "\n".join(sql_text.split("\n")[1:]).strip()
            if sql_text:
                queries.append((f"Query_{query_id}", sql_text.rstrip(";").strip()))
        return queries

    # Format 2: plain SQL statements separated by ';'
    statement_lines: List[str] = []
    q_idx = 1
    for raw in content.splitlines():
        s = raw.strip()
        if not s or s.startswith("--"):
            continue
        statement_lines.append(raw)
        if ";" in raw:
            sql_text = "\n".join(statement_lines).strip().rstrip(";").strip()
            if sql_text:
                queries.append((f"Query_{q_idx}", sql_text))
                q_idx += 1
            statement_lines = []

    # Trailing statement without semicolon.
    if statement_lines:
        sql_text = "\n".join(statement_lines).strip()
        if sql_text:
            queries.append((f"Query_{q_idx}", sql_text))

    return queries


def collect_training_workload(dataset_query: str) -> List[str]:
    """Collect training queries from Data/Player/player_queries.sql."""
    all_queries = []
    base = PROJECT_ROOT / "Data" / dataset_query
    queries_file = base / f"{dataset_query.lower()}_queries.sql"
    
    if queries_file.exists():
        logger.info(f"Loading training queries from {queries_file}")
        for _qid, qtext in load_sql_queries(queries_file):
            all_queries.append(qtext)
    else:
        logger.error(f"Training queries file not found: {queries_file}")
        
    logger.info(f"Total training queries collected: {len(all_queries)}")
    return all_queries


def verify_data_availability(dataset: str) -> bool:
    """Verify that source data exists."""
    data_dir = SOURCE_DATA_DIR / dataset
    if not data_dir.exists():
        logger.error(f"Source data directory not found: {data_dir}")
        return False
    data_files = list(data_dir.glob("**/*.txt"))
    if not data_files:
        logger.error(f"No text files found in {data_dir}")
        return False
    logger.info(f"Found {len(data_files)} source documents in {data_dir}")
    return True


def run_preprocessing_phase(
    dataset: str,
    dataset_query: str,
    run_dir: Path,
    *,
    projection_fastpath: bool = False,
    projection_fastpath_col_batch_size: int = 0,
) -> Tuple[bool, Dict[str, Any]]:
    """
    Run offline relational synthesis. DB and cache are written under run_dir.
    """
    import config as config_module
    import shutil

    logger.info("=" * 80)
    logger.info("OFFLINE RELATIONAL SYNTHESIS (Preprocessing)")
    logger.info("=" * 80)

    phase_start = time.time()
    stats = {
        "dataset": dataset,
        "dataset_query": dataset_query,
        "training_workload": TRAINING_QUERY_TYPES,
        "run_dir": str(run_dir),
        "steps": {},
    }

    try:
        if not verify_data_availability(dataset):
            logger.error("Data verification failed")
            return False, stats

        logger.info(f"\nCollecting training queries from {TRAINING_QUERY_TYPES}")
        training_queries = collect_training_workload(dataset_query)
        if not training_queries:
            logger.error("No training queries collected!")
            return False, stats

        logger.info(f"Collected {len(training_queries)} training queries")

        # Redirect all outputs to this run's directory
        cache_dir = run_dir / ".cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        original_cache = config_module.CACHE_DIR
        config_module.CACHE_DIR = cache_dir

        db_path = run_dir / "wdirs.db"
        postgres_uri = f"sqlite:///{db_path}"

        try:
            logger.info(f"\nOutput directory: {run_dir}")
            logger.info(f"  DB: {db_path}")
            logger.info(f"  Cache: {cache_dir}")

            runner = WDIRSRunner(
                dataset=dataset,
                postgres_uri=postgres_uri,
                use_projection_fastpath=projection_fastpath,
                projection_fastpath_col_batch_size=projection_fastpath_col_batch_size,
                cache_dir=cache_dir,  # keep attribute index co-located with extractions
            )

            logger.info("\nRunning unified preprocessing pipeline...")
            step_start = time.time()
            preprocessing_result = runner.preprocess(workload_queries=training_queries)
            step_time = time.time() - step_start

            if not preprocessing_result.success:
                logger.error(f"Preprocessing failed: {preprocessing_result.error}")
                stats["success"] = False
                stats["error"] = preprocessing_result.error
                stats["total_time"] = step_time
                return False, stats

            stats["steps"]["preprocessing"] = {
                "time": step_time,
                "tables_processed": len(preprocessing_result.tables_processed),
                "total_chunks": preprocessing_result.total_chunks,
                "total_records": preprocessing_result.total_records,
                "tables": preprocessing_result.tables_processed,
            }
            logger.info(f"✓ Preprocessing complete in {step_time:.2f}s")
            logger.info(f"  - Tables: {preprocessing_result.tables_processed}")
            logger.info(f"  - Chunks: {preprocessing_result.total_chunks}")
            logger.info(f"  - Records: {preprocessing_result.total_records}")

            # Save artifacts into run_dir
            checkpoint_path = run_dir / f"{dataset}_preprocessed.db"
            shutil.copy2(db_path, checkpoint_path)
            logger.info(f"Saved checkpoint to {checkpoint_path}")

            identity_file = run_dir / f"{dataset}_identity_columns.json"
            identity_payload = dict(runner.identity_columns)
            with open(identity_file, "w") as f:
                json.dump(identity_payload, f, indent=2)
            logger.info(f"Saved identity column map to {identity_file}: {identity_payload}")

            stats["steps"]["save_checkpoint"] = {
                "time": 0.0,
                "checkpoint_path": str(checkpoint_path),
            }
            if checkpoint_path.exists():
                stats["steps"]["save_checkpoint"]["checkpoint_size_mb"] = (
                    checkpoint_path.stat().st_size / (1024 * 1024)
                )

        finally:
            config_module.CACHE_DIR = original_cache

        total_time = time.time() - phase_start
        stats["total_time"] = total_time
        stats["success"] = True

        stats_file = run_dir / f"{dataset}_preprocessing_stats.json"
        with open(stats_file, "w") as f:
            json.dump(stats, f, indent=2)
        logger.info(f"Saved preprocessing stats to {stats_file}")

        logger.info("\n" + "=" * 80)
        logger.info(f"PREPROCESSING COMPLETE - Total Time: {total_time:.2f}s")
        logger.info("=" * 80)

        return True, stats

    except Exception as e:
        logger.exception(f"Preprocessing phase failed: {e}")
        stats["success"] = False
        stats["error"] = str(e)
        stats["total_time"] = time.time() - phase_start
        return False, stats


def main(
    projection_fastpath: bool = False,
    projection_fastpath_col_batch_size: int = 0,
) -> int:
    """Create a timestamped run dir, run preprocessing, and save token report."""
    ensure_precise_tokenizer_ready()

    run_tag = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RUN_BASE_DIR / f"run_{run_tag}"
    run_dir.mkdir(parents=True, exist_ok=True)
    log_file = run_dir / "preprocess.log"
    setup_logging(log_file)

    logger.info("WDIRS Player workload preprocessing (preprocessing only)")
    logger.info(f"Dataset: {DATASET}")
    logger.info(f"Query Dataset: {DATASET_QUERY}")
    logger.info(f"Run directory: {run_dir}")
    logger.info(f"Log file: {log_file}")
    logger.info(f"Source data: {SOURCE_DATA_DIR / DATASET}")
    logger.info(f"Query directory: {QUERY_DIR / DATASET_QUERY}")
    logger.info(
        "Projection fast path: %s (col_batch_size=%s)",
        projection_fastpath,
        projection_fastpath_col_batch_size,
    )

    success, stats = run_preprocessing_phase(
        DATASET,
        DATASET_QUERY,
        run_dir,
        projection_fastpath=projection_fastpath,
        projection_fastpath_col_batch_size=projection_fastpath_col_batch_size,
    )

    # Token cost report
    token_summary = GLOBAL_COUNTER.summary_str()
    logger.info(token_summary)
    token_json_path = run_dir / "token_cost.json"
    GLOBAL_COUNTER.save_json(token_json_path)
    logger.info(f"Token cost JSON saved to: {token_json_path}")

    logger.info("=" * 80)
    logger.info(f"Results saved to: {run_dir}")
    logger.info("=" * 80)

    return 0 if success else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run WDIRS Player workload preprocessing only.")
    parser.add_argument(
        "--projection-fastpath",
        action="store_true",
        help="Use source-doc projection fast path during extraction.",
    )
    parser.add_argument(
        "--projection-fastpath-col-batch-size",
        type=int,
        default=0,
        help="Column batch size for projection fast path (0 = all columns in one call).",
    )
    args = parser.parse_args()
    sys.exit(
        main(
            projection_fastpath=args.projection_fastpath,
            projection_fastpath_col_batch_size=args.projection_fastpath_col_batch_size,
        )
    )
