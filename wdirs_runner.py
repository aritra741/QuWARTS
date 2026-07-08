"""
WDIRS Runner - Main orchestration module.
Integrates all components and provides the main interface.
"""

import json
import logging
import time
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from dataclasses import dataclass, asdict
import sys

from sqlalchemy import text as _sa_text
from data_layer import DataLayer, TextChunk
from lattice_planner import LatticePlanner, load_workload_from_directory
from sieve_synthesizer import SieveSynthesizer
from extractor import ConstrainedExtractor, OllamaClient
from entity_resolver import EntityResolver, extract_mentions_from_records, apply_canonical_map
from delta_engine import DeltaEngine, DeltaType
from entity_anchor import detect_identity_column

from config import (
    SOURCE_DATA_DIR,
    QUERY_DIR,
    get_dataset_path,
    get_schema_path,
    get_workload_path,
    CACHE_DIR,
    LOG_LEVEL,
    LOG_FORMAT,
    LOG_FILE,
    USE_PROJECTION_FASTPATH,
    PROJECTION_FASTPATH_COL_BATCH_SIZE,
)

# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format=LOG_FORMAT,
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class PreprocessingResult:
    """Result of preprocessing phase."""
    success: bool
    tables_processed: List[str]
    total_chunks: int
    total_records: int
    preprocessing_time: float
    error: Optional[str] = None

@dataclass
class QueryResult:
    """Result of query execution."""
    success: bool
    results: List[Dict[str, Any]]
    delta_type: str
    rows_extracted: int
    rows_enriched: int
    execution_time: float
    error: Optional[str] = None


# ============================================================================
# Helper Functions
# ============================================================================

def semantic_to_sql_type(semantic_type: str) -> str:
    """Convert semantic type to SQL type."""
    type_map = {
        "PERSON": "TEXT",
        "ORG": "TEXT",
        "DATE": "TEXT",
        "GPE": "TEXT",
        "CODE": "TEXT",
        "MONEY": "REAL",
        "QUANTITY": "REAL",
        "QUANTITY_COUNT": "REAL",
        "PRODUCT": "TEXT",
        "EVENT": "TEXT",
        "OTHER": "TEXT"
    }
    return type_map.get(semantic_type, "TEXT")


_NUMERIC_SQL_TYPES = {"REAL", "INTEGER", "NUMERIC", "INT", "FLOAT", "DOUBLE"}


def _validate_record(
    record: Dict[str, Any],
    sql_schema: Dict[str, str],
    chunk_texts: List[str],
    identity_col: str,
    spans: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """
    Validate and clean one extracted record before writing to the DB.

    Two checks are applied to every non-null, non-identity cell:

    1. Type check (hard)
       REAL/INTEGER/NUMERIC columns must hold a value castable to float
       (after stripping commas and percent signs).  Failures are dropped.

    2. Span grounding (evidence check)
       Priority order:
         a) If the LLM returned a supporting span for this field (from the
            span-grounded prompt format), verify that span appears verbatim
            (case-insensitive) in the source chunks.  Because the span is an
            exact quote, any mismatch means the LLM fabricated it.
         b) If no span was returned (old-format response or Pass-1 call),
            fall back to checking that the value string itself appears in
            the source chunks.  This is weaker but better than nothing.
       JSON-shaped values ([... or {...) are always rejected — the LLM
       should never return structured collections for a flat table cell.

    The identity column is exempt — it is stamped by entity resolution.
    """
    if not chunk_texts:
        return record

    corpus = " ".join(t.lower() for t in chunk_texts)
    spans = spans or {}

    validated: Dict[str, Any] = {}
    for col, val in record.items():
        if col in ("_entity", "row_id", identity_col):
            validated[col] = val
            continue
        if val is None:
            continue

        sql_type = sql_schema.get(col, "TEXT").upper()

        if sql_type in _NUMERIC_SQL_TYPES:
            try:
                float(str(val).replace(",", "").replace("%", "").strip())
                validated[col] = val
            except (ValueError, TypeError):
                logger.debug(f"[Validate] Dropped '{col}'={val!r}: expected numeric")
        else:
            val_str = str(val).strip()
            if len(val_str) < 2:
                continue
            if val_str.startswith("[") or val_str.startswith("{"):
                logger.debug(f"[Validate] Dropped '{col}'={val_str[:60]!r}: JSON shape")
                continue

            # Prefer span check; fall back to value check.
            span = spans.get(col, "")
            if span:
                if span.lower() in corpus:
                    validated[col] = val
                else:
                    logger.debug(
                        f"[Validate] Dropped '{col}'={val_str[:40]!r}: "
                        f"span {span[:40]!r} not found in source chunks"
                    )
            else:
                # No span provided — check value itself as a fallback.
                if val_str.lower() in corpus:
                    validated[col] = val
                else:
                    logger.debug(
                        f"[Validate] Dropped '{col}'={val_str[:60]!r}: "
                        f"no span, value not in chunks"
                    )

    return validated


# ============================================================================
# WDIRS Runner
# ============================================================================

class WDIRSRunner:
    """
    Main orchestrator for WDIRS system.
    Coordinates all phases of the pipeline.
    """
    
    def __init__(
        self,
        dataset: str,
        postgres_uri: Optional[str] = None,
        use_projection_fastpath: Optional[bool] = None,
        projection_fastpath_col_batch_size: Optional[int] = None,
        cache_dir: Optional[Path] = None,
    ):
        """
        Initialize WDIRS runner.
        
        Args:
            dataset: Name of the dataset
            postgres_uri: Optional PostgreSQL connection URI
            cache_dir: Optional cache directory (defaults to CACHE_DIR / dataset)
        """
        self.dataset = dataset
        self.use_projection_fastpath = (
            USE_PROJECTION_FASTPATH
            if use_projection_fastpath is None
            else bool(use_projection_fastpath)
        )
        self.projection_fastpath_col_batch_size = (
            PROJECTION_FASTPATH_COL_BATCH_SIZE
            if projection_fastpath_col_batch_size is None
            else int(projection_fastpath_col_batch_size)
        )
        
        # Set cache directory (for attribute index and other cached artifacts)
        if cache_dir is not None:
            self.cache_dir = Path(cache_dir) / dataset if not str(cache_dir).endswith(dataset) else Path(cache_dir)
        else:
            self.cache_dir = CACHE_DIR / dataset
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"Initializing WDIRS for dataset: {dataset}")
        logger.info(f"Cache directory: {self.cache_dir}")
        logger.info(
            "Projection fast path: %s (col_batch_size=%s)",
            self.use_projection_fastpath,
            self.projection_fastpath_col_batch_size,
        )
        
        # Initialize components
        self.data_layer = DataLayer(postgres_uri) if postgres_uri else DataLayer()
        self.llm_client = OllamaClient()
        self.lattice_planner = LatticePlanner(self.llm_client)
        self.sieve_synthesizer = SieveSynthesizer(self.llm_client)
        self.extractor = ConstrainedExtractor(self.llm_client)
        self.entity_resolver = EntityResolver(self.llm_client)
        self.delta_engine = DeltaEngine(
            self.data_layer,
            self.lattice_planner,
            self.extractor,
            self.entity_resolver
        )
        
        # Identity columns detected/discovered per table.
        # Populated by _build_identity_map before extraction.
        # None value means the table has no reliable identity column (rare).
        self.identity_columns: Dict[str, Optional[str]] = {}

        # spaCy NER label for each table's identity column.
        # Used by entity-first extraction to group chunks by entity without LLM.
        self.identity_ner_labels: Dict[str, Optional[str]] = {}
        # Share live identity map with delta engine for runtime upserts.
        self.delta_engine.identity_columns = self.identity_columns

        # Load spaCy model once; reused for all NER passes.
        import spacy as _spacy
        try:
            self._nlp = _spacy.load("en_core_web_sm")
            logger.info("spaCy en_core_web_sm loaded for entity-first extraction")
        except OSError:
            raise RuntimeError(
                "spaCy model 'en_core_web_sm' not found. "
                "Run: python -m spacy download en_core_web_sm"
            )
        
        logger.info("WDIRS initialization complete")
    
    # ========================================================================
    # Phase 1: Offline Relational Synthesis (Preprocessing)
    # ========================================================================
    
    def preprocess(
        self,
        workload_queries: Optional[List[str]] = None
    ) -> PreprocessingResult:
        """
        Run complete preprocessing pipeline.
        
        Args:
            workload_queries: Optional list of SQL queries. If not provided, loads from Query directory.
            
        Returns:
            PreprocessingResult
        """
        logger.info("=" * 80)
        logger.info("PHASE 1: OFFLINE RELATIONAL SYNTHESIS")
        logger.info("=" * 80)
        
        start_time = time.time()
        
        try:
            # Step 1: Load and parse workload
            logger.info("\n[Step 1/6] Loading workload...")
            if workload_queries is None:
                workload_path = str(QUERY_DIR / self.dataset)
                from lattice_planner import load_workload_from_directory
                workload_queries = load_workload_from_directory(workload_path)
            
            lattice = self.lattice_planner.parse_workload(workload_queries)
            
            total_columns = sum(len(t.columns) for t in lattice.tables.values())
            logger.info(f"Workload parsed: {len(lattice.tables)} tables, {total_columns} columns")
            
            # Check if we have columns
            if total_columns == 0:
                logger.warning("No columns extracted from workload! This will result in no data extraction.")
                logger.warning("Sample queries:")
                for i, q in enumerate(workload_queries[:3]):
                    logger.warning(f"  Query {i+1}: {q[:100]}...")
            
            # Log table details
            for table_name, table_info in lattice.tables.items():
                logger.info(f"  Table '{table_name}': {len(table_info.columns)} columns - {list(table_info.columns.keys())}")
            
            # Step 2: Ingest text data
            logger.info("\n[Step 2/6] Ingesting text data...")
            total_chunks = self._ingest_text_data()
            logger.info(f"Ingested {total_chunks} chunks")
            
            # Step 3: Synthesize sieves
            logger.info("\n[Step 3/7] Synthesizing programmatic sieves...")
            self._synthesize_sieves(lattice)

            # Step 3.5: Detect identity columns — must happen after sieves so
            # we have candidate chunks available for Evaporate-style fallback.
            logger.info("\n[Step 4/7] Detecting entity identity columns...")
            self._build_identity_map(lattice)

            # Step 4: Global extraction
            logger.info("\n[Step 5/7] Performing constrained global extraction...")
            total_records = self._global_extraction(lattice)
            logger.info(f"Extracted {total_records} records")

            # Step 5.5: Record consolidation — merge any remaining duplicates
            logger.info("\n[Step 6/7] Consolidating extracted records (deduplication + merging)...")
            self._consolidate_records(lattice)

            # Step 6: Entity resolution on join keys
            logger.info("\n[Step 7/7] Performing proactive entity resolution...")
            self._proactive_entity_resolution(lattice)

            # Step 7: Save preprocessing results
            logger.info("\n[Step 8/8] Saving preprocessing results...")
            self._save_preprocessing_results(lattice)
            
            preprocessing_time = time.time() - start_time
            
            result = PreprocessingResult(
                success=True,
                tables_processed=list(lattice.tables.keys()),
                total_chunks=total_chunks,
                total_records=total_records,
                preprocessing_time=preprocessing_time
            )
            
            logger.info("=" * 80)
            logger.info("PREPROCESSING COMPLETE")
            logger.info(f"Time: {preprocessing_time:.2f}s")
            logger.info(f"Tables: {len(lattice.tables)}")
            logger.info(f"Chunks: {total_chunks}")
            logger.info(f"Records: {total_records}")
            logger.info("=" * 80)
            
            return result
        
        except Exception as e:
            logger.error(f"Preprocessing failed: {e}", exc_info=True)
            preprocessing_time = time.time() - start_time
            
            return PreprocessingResult(
                success=False,
                tables_processed=[],
                total_chunks=0,
                total_records=0,
                preprocessing_time=preprocessing_time,
                error=str(e)
            )
    
    def _ingest_text_data(self) -> int:
        """
        Ingest all source text files into the chunk store, in parallel.

        Files are read and chunked concurrently (CPU-bound, GIL is released by
        the splitter).  DB writes are batched and serialised — SQLite does not
        support concurrent writers, so we collect all chunks from a worker pool
        and flush to DB in a single call per batch.

        Duplicate (doc_id, chunk_index) pairs are silently ignored by
        insert_chunks (INSERT OR IGNORE), so re-running ingest is idempotent.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed as _asc
        from config import MAX_PARALLEL_REQUESTS

        dataset_path = get_dataset_path(self.dataset)
        if not dataset_path.exists():
            logger.warning(f"Dataset path not found: {dataset_path}")
            return 0

        text_files = list(dataset_path.glob("**/*.txt"))
        logger.info(
            f"[Ingest] {len(text_files)} source files, "
            f"{MAX_PARALLEL_REQUESTS} reader threads"
        )

        def _read_and_chunk(text_file):
            try:
                doc_id = str(text_file.relative_to(dataset_path))
                content = text_file.read_text(encoding="utf-8", errors="replace")
                return self.data_layer.create_chunks(
                    content, doc_id, metadata={"source_file": str(text_file)}
                )
            except Exception as exc:
                logger.error(f"[Ingest] Error reading {text_file}: {exc}")
                return []

        total_chunks = 0
        DB_BATCH = 200  # files per DB flush — balances RAM vs round-trip cost

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
            futs = {pool.submit(_read_and_chunk, f): f for f in text_files}
            pending_chunks: list = []
            done = 0
            for fut in _asc(futs):
                chunks = fut.result()
                pending_chunks.extend(chunks)
                done += 1
                if done % DB_BATCH == 0:
                    if pending_chunks:
                        self.data_layer.insert_chunks(pending_chunks)
                        total_chunks += len(pending_chunks)
                        pending_chunks = []
                    logger.info(f"[Ingest] {done}/{len(text_files)} files processed")

        # Flush remainder
        if pending_chunks:
            self.data_layer.insert_chunks(pending_chunks)
            total_chunks += len(pending_chunks)

        logger.info(f"[Ingest] Done: {total_chunks} chunks from {len(text_files)} files")
        return total_chunks
    
    def _synthesize_sieves(self, lattice) -> None:
        """Synthesize sieves and apply them via streaming + parallel evaluation."""
        from config import MAX_PARALLEL_REQUESTS

        # Count once — used for ETA logging across all tables.
        total_chunks = self.data_layer.count_chunks()
        logger.info(f"[Sieve] Corpus size: {total_chunks:,} chunks")

        for table_name, table_info in lattice.tables.items():
            try:
                # ── Synthesis ────────────────────────────────────────────────
                # 50 random-ish chunks give better keyword coverage than 10.
                sample_chunks_objs = self.data_layer.get_all_chunks(limit=50)
                sample_chunks = [c.content for c in sample_chunks_objs]
                schema = self.lattice_planner.get_table_schema(table_name)

                sieve_result = self.sieve_synthesizer.synthesize_sieve(
                    table_name, schema, sample_chunks
                )
                logger.info(
                    f"[Sieve] Synthesized sieve for '{table_name}' "
                    f"(accuracy: {sieve_result.accuracy:.2%})"
                )

                # ── Streaming parallel application ───────────────────────────
                # Stream the corpus page-by-page (10k chunks at a time) and
                # evaluate each page with a thread pool.  spaCy and regex both
                # release the GIL so threads give near-linear speedup on the
                # Blackwell GPU node's many CPU cores.
                logger.info(
                    f"[Sieve] Applying sieve to {total_chunks:,} chunks for "
                    f"'{table_name}' using {MAX_PARALLEL_REQUESTS} threads …"
                )
                page_iter = self.data_layer.stream_chunks_paged(page_size=10_000)
                candidate_ids = self.sieve_synthesizer.apply_sieve_streamed(
                    table_name,
                    page_iter,
                    total_chunks,
                    max_workers=MAX_PARALLEL_REQUESTS,
                )

                # ── Insert candidates ────────────────────────────────────────
                self.data_layer.insert_candidates(table_name, candidate_ids)
                logger.info(
                    f"[Sieve] Indexed {len(candidate_ids):,} candidate chunks "
                    f"for '{table_name}'"
                )

            except Exception as e:
                logger.error(f"Error synthesizing sieve for {table_name}: {e}")
                raise RuntimeError(
                    f"Sieve synthesis failed for table '{table_name}': {e}"
                ) from e
    
    def _build_identity_map(self, lattice) -> None:
        """
        Detect the primary identity column for every table in the lattice.

        Three-tier strategy, each tier falling through to the next only if it
        produces no result:

        Tier 1 — Semantic-type pre-filter (zero LLM cost):
          The lattice planner already ran _identify_semantic_types and tagged
          every column as PERSON, ORG, GPE, DATE, etc.  The identity column is
          almost always the one with a PERSON, ORG, or GPE tag.  Collect those
          candidates and, if exactly one exists, use it directly.  If several
          exist, pass only those to the LLM (Tier 2) — much easier than 25+.

        Tier 2 — LLM on pre-filtered candidates:
          Ask the LLM to pick from the short candidate list (typically 1-3
          columns).  This is reliable even for 7B models because the list is
          small and all candidates are plausible identity types.

        Tier 3 — Evaporate-style text discovery (last resort):
          Used only when the workload has NO PERSON/ORG/GPE column at all
          (e.g. pure aggregation queries with no entity reference).  Samples
          raw text chunks and discovers the entity attribute by field frequency.

        Results are stored in self.identity_columns[table_name].
        """
        ENTITY_SEMANTIC_TYPES = {"PERSON", "ORG", "GPE"}

        for table_name, table_info in lattice.tables.items():
            schema = self.lattice_planner.get_table_schema(table_name)
            schema_columns = list(schema.keys())

            logger.info(
                f"[IdentityMap] Detecting identity column for '{table_name}' "
                f"({len(schema_columns)} columns): {schema_columns}"
            )

            # --- Tier 1: semantic-type pre-filter ---
            # Intentionally NOT restricted to schema_columns: a query like
            # "SELECT earnings_per_share FROM finance" omits company_name from
            # the SELECT, but company_name is still the entity anchor for the
            # whole table.  We look at ALL typed columns in table_info so the
            # identity column is found even when it wasn't queried.
            entity_candidates = [
                col for col, col_info in table_info.columns.items()
                if getattr(col_info, "semantic_type", "OTHER") in ENTITY_SEMANTIC_TYPES
            ]

            logger.info(
                f"[IdentityMap] Tier-1 entity candidates for '{table_name}': "
                f"{entity_candidates}"
            )

            identity_col: Optional[str] = None

            if len(entity_candidates) == 1:
                # Unambiguous — no LLM call needed.
                identity_col = entity_candidates[0]
                logger.info(
                    f"[IdentityMap] Single entity candidate → '{identity_col}' "
                    f"(no LLM call needed)"
                )
            elif len(entity_candidates) > 1:
                # --- Tier 2a: Tournament LLM on pre-filtered entity candidates ---
                # Columns compete in groups of TOURNAMENT_GROUP_SIZE; the LLM
                # picks the best identity column from each group and winners
                # advance until one remains.  Guaranteed to produce a result as
                # long as Ollama is reachable — no heuristic fallback needed.
                identity_col = detect_identity_column(
                    table_name,
                    entity_candidates,
                    self.extractor.llm_client,
                )
            else:
                # No PERSON/ORG/GPE columns at all — run the tournament on the
                # full schema so the LLM can pick the most entity-like column
                # from whatever is available.
                # --- Tier 2b: Tournament LLM on full schema ---
                identity_col = detect_identity_column(
                    table_name,
                    schema_columns,
                    self.extractor.llm_client,
                )

            if identity_col is None:
                # --- Tier 3: NER-based entity type detection ---
                # Reached only when entity_candidates AND schema_columns are
                # both empty, or Ollama is completely unreachable and the
                # tournament stall-safety path also returned None.
                # Legitimate case: pure aggregation schema (GROUP BY exchange_code)
                # with no column that could name an entity at all.  spaCy NER
                # identifies the dominant entity type in candidate text so
                # _global_extraction knows to use plain INSERTs (no upsert key).
                logger.info(
                    f"[IdentityMap] No entity column in schema for '{table_name}'. "
                    f"Running NER-based entity type detection (Tier 3)..."
                )
                candidate_chunk_ids = self.data_layer.get_candidates(table_name)
                if not candidate_chunk_ids:
                    logger.warning(
                        f"[IdentityMap] No candidate chunks for '{table_name}'. "
                        f"Skipping entity detection."
                    )
                    self.identity_columns[table_name] = None
                    continue

                sample_chunks = self.data_layer.get_chunks_by_ids(
                    candidate_chunk_ids[:50]
                )
                sample_texts = [c.content for c in sample_chunks]

                # Count named-entity types across the sample
                from collections import Counter as _Counter
                ner_type_counts: _Counter = _Counter()
                for doc in self._nlp.pipe(
                    sample_texts, batch_size=32,
                    disable=["parser", "lemmatizer"]
                ):
                    for ent in doc.ents:
                        if ent.label_ in {"PERSON", "ORG", "GPE"}:
                            ner_type_counts[ent.label_] += 1

                if ner_type_counts:
                    dominant_type = ner_type_counts.most_common(1)[0][0]
                    # Store the NER label only — no real DB identity column
                    # exists for this table, so identity_col stays None.
                    # _global_extraction will take the brute-force path
                    # (plain INSERTs).  The NER label is recorded so that
                    # _group_chunks_by_entity can still group for efficiency
                    # when called explicitly; it is NOT used for DB upserts.
                    logger.info(
                        f"[IdentityMap] Tier-3 NER: dominant entity type for "
                        f"'{table_name}' is {dominant_type} "
                        f"(counts: {dict(ner_type_counts.most_common(3))}). "
                        f"No real identity column — brute-force extraction."
                    )
                    # Expose the dominant NER type via a sentinel on table_info
                    # so ner_label derivation below can pick it up without
                    # polluting the column schema.
                    table_info._tier3_ner_type = dominant_type  # type: ignore[attr-defined]
                else:
                    logger.warning(
                        f"[IdentityMap] Tier-3 NER found no named entities in "
                        f"sample chunks for '{table_name}'. "
                        f"Using brute-force plain insert."
                    )

            # Derive the spaCy NER label from the LLM-assigned semantic type of
            # the identity column.  The semantic type was determined by
            # _identify_semantic_types during parse_workload.
            # We then cross-check against workload normalization hint values to
            # catch the common case where the LLM mistakenly labels an ORG
            # column (e.g. company_name) as PERSON.  Value-based detection is
            # dataset-agnostic and requires no extra LLM call.
            ner_label: Optional[str] = None
            if identity_col and identity_col in table_info.columns:
                sem_type = getattr(
                    table_info.columns[identity_col], "semantic_type", None
                )
                ner_label = self._semantic_type_to_ner_label(sem_type)

                # Dataset-agnostic hint cross-check:
                # infer NER type from literal hint values using spaCy, then
                # reconcile the semantic-type-derived label when evidence is strong.
                _norm_hints = self.lattice_planner.get_normalization_hints(table_name)
                _hint_vals = _norm_hints.get(identity_col, [])
                inferred_label = self._infer_ner_label_from_hints(_hint_vals)
                if inferred_label and ner_label != inferred_label:
                    logger.info(
                        f"[IdentityMap] Hint-based NER correction for "
                        f"'{identity_col}': {ner_label} → {inferred_label}"
                    )
                    ner_label = inferred_label

            elif hasattr(table_info, "_tier3_ner_type"):
                # Tier-3 case: NER type discovered from text but no real DB column.
                ner_label = self._semantic_type_to_ner_label(
                    table_info._tier3_ner_type  # type: ignore[attr-defined]
                )

            self.identity_columns[table_name] = identity_col
            self.identity_ner_labels[table_name] = ner_label
            logger.info(
                f"[IdentityMap] '{table_name}' → identity_col='{identity_col}', "
                f"ner_label='{ner_label}'"
            )

    @staticmethod
    def _semantic_type_to_ner_label(semantic_type: Optional[str]) -> Optional[str]:
        """
        Map a lattice-planner semantic type to its spaCy NER label.

        Semantic types are assigned by the LLM during parse_workload and are
        fully dataset-agnostic (PERSON, ORG, GPE, etc.).  This mapping is the
        single source of truth for how we translate those types into spaCy's
        entity label vocabulary.

        Returns None for types that have no direct NER analogue (CODE, DATE,
        QUANTITY, OTHER) — in that case _group_chunks_by_entity sweeps all
        named-entity types.
        """
        _MAP = {
            "PERSON":   "PERSON",
            "ORG":      "ORG",
            "GPE":      "GPE",
            "PRODUCT":  "PRODUCT",
            "EVENT":    "EVENT",
            "MONEY":          "MONEY",
            "QUANTITY":       "QUANTITY",
            "QUANTITY_COUNT": "QUANTITY",  # treat like QUANTITY for NER grouping
            # DATE, CODE, OTHER have no reliable spaCy analogue; use all types.
        }
        return _MAP.get(semantic_type) if semantic_type else None

    def _infer_ner_label_from_hints(self, hint_values: List[str]) -> Optional[str]:
        """
        Infer coarse NER label (PERSON/ORG/GPE) from predicate hint literals.

        This avoids dataset-specific hardcoded suffix/pattern lists.
        Returns None when hint evidence is weak.
        """
        from collections import Counter

        vals = [str(v).strip() for v in (hint_values or []) if str(v).strip()]
        if not vals:
            return None

        labels = []
        for doc in self._nlp.pipe(vals[:30], batch_size=30, disable=["parser", "lemmatizer"]):
            ents = [e for e in doc.ents if e.label_ in {"PERSON", "ORG", "GPE"}]
            if not ents:
                continue
            ents.sort(key=lambda e: len(e.text), reverse=True)
            labels.append(ents[0].label_)

        if not labels:
            return None

        top_label, top_count = Counter(labels).most_common(1)[0]
        if top_count >= 2 and top_count / len(labels) >= 0.60:
            return top_label
        return None

    def _identity_pass(
        self,
        table_name: str,
        identity_col: str,
        candidate_chunks: list,
        predicate_hints: Optional[List[str]] = None,
        ner_label: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """
        Pass 1: extract the identity column value from every candidate chunk.
        Returns a mapping of raw_entity_value → [chunk_ids].

        Engine selection
        ────────────────
        spaCy NER is used as the primary engine.  It processes millions of
        tokens per minute on GPU (via nlp.pipe with batch_size tuned to VRAM),
        reducing a 13-hour LLM Pass 1 to roughly 10-20 minutes for 2.4M chunks.

        spaCy's output is filtered to the semantic NER label that corresponds to
        the identity column's type (ORG for company_name, PERSON for author, GPE
        for country, etc.).  This is the same label already derived in
        _build_identity_map and is passed in as `ner_label`.

        When `ner_label` is None (DATE, CODE, OTHER — types with no direct spaCy
        analogue), all entity types are considered.

        Predicate hints as normalization anchors
        ─────────────────────────────────────────
        The raw NER surface form ("The United States of America") is compared
        against predicate_hints ("USA") at entity-resolution time, not here.
        Here hints are only used as a secondary check: if a chunk contains a
        known predicate literal verbatim, it is attributed to that entity even
        if NER did not extract anything.  This makes Pass 1 query-aware without
        restricting what gets extracted.

        Zero LLM calls
        ──────────────
        The LLM is no longer invoked in Pass 1.  Entity resolution (bi-encoder +
        cross-encoder) in _group_chunks_by_entity handles deduplication and alias
        collapsing on the raw NER output.
        """
        from config import NER_BATCH_SIZE  # default 256, tunable via env var

        raw: Dict[str, List[str]] = {}  # entity_value → [chunk_ids]
        total = len(candidate_chunks)

        # NER labels to accept; None means accept all entity types.
        accept_labels: Optional[set] = (
            {ner_label} if ner_label else None
        )
        # Additional spaCy labels that are always useful alongside the primary type
        # (e.g. if primary is ORG, PERSON and GPE can sometimes fill the same role).
        if ner_label == "ORG":
            accept_labels = {"ORG"}   # strict: only ORG for company_name
        elif ner_label == "PERSON":
            accept_labels = {"PERSON"}
        elif ner_label == "GPE":
            accept_labels = {"GPE", "LOC", "NORP"}  # countries + demonyms

        # Build hint set for verbatim-match fallback (query-aware).
        hint_set: set = {h.lower().strip() for h in (predicate_hints or [])}

        logger.info(
            f"[Pass1-NER] Extracting '{identity_col}' (label={ner_label}) "
            f"from {total:,} chunks for '{table_name}' "
            f"using spaCy NER (batch_size={NER_BATCH_SIZE})"
        )

        texts   = [c.content for c in candidate_chunks]
        cids    = [c.chunk_id for c in candidate_chunks]

        done = 0
        # nlp.pipe releases the GIL and uses GPU when spaCy is GPU-enabled.
        for doc, chunk_id in zip(
            self._nlp.pipe(
                texts,
                batch_size=NER_BATCH_SIZE,
                disable=["parser", "lemmatizer"],
            ),
            cids,
        ):
            done += 1
            if done % 50_000 == 0 or done == total:
                logger.info(f"[Pass1-NER] {done:,}/{total:,} chunks processed")

            # Collect all entity mentions that match the target label.
            found: List[str] = []
            for ent in doc.ents:
                if accept_labels is None or ent.label_ in accept_labels:
                    name = ent.text.strip()
                    if len(name) >= 2:
                        found.append(name)

            if found:
                # Use the most-frequent entity in this chunk as the primary value.
                from collections import Counter as _C
                primary = _C(found).most_common(1)[0][0]
                raw.setdefault(primary, []).append(chunk_id)
            elif hint_set:
                # Verbatim-hint fallback: if a known predicate literal appears in
                # the chunk text, attribute the chunk to that entity even though
                # NER returned nothing.  Case-insensitive substring match only.
                text_lower = doc.text.lower()
                for hint in predicate_hints or []:
                    if hint.lower() in text_lower:
                        raw.setdefault(hint, []).append(chunk_id)
                        break  # attribute to the first matching hint only

        non_null = sum(len(v) for v in raw.values())
        logger.info(
            f"[Pass1-NER] Done: {len(raw):,} unique raw entity values, "
            f"{non_null:,}/{total:,} chunks had a match"
        )
        return raw

    def _doc_level_identity_pass(
        self,
        table_name: str,
        identity_col: str,
        candidate_chunks: list,
        predicate_hints: Optional[List[str]] = None,
        ner_label: Optional[str] = None,
    ) -> Dict[str, List[str]]:
        """
        Deterministic low-cost document-level Pass 1.

        For each source document:
          1) Build a fixed-budget extractive summary (model-assisted).
          2) Classify the summary to one table among all workload tables.
          3) If class == current table, extract one identity value (top-1)
             from the summary only.

        No confidence gating and no full-document / NER fallback — cost is
        predictable and bounded per document.
        """
        import re as _re
        from concurrent.futures import ThreadPoolExecutor, as_completed as _asc
        from config import MAX_PARALLEL_REQUESTS

        dataset_path = get_dataset_path(self.dataset)

        # Group chunks by source document.
        doc_to_chunks: Dict[str, list] = {}
        for chunk in candidate_chunks:
            doc_to_chunks.setdefault(chunk.doc_id, []).append(chunk)

        n_docs = len(doc_to_chunks)

        def _doc_prefix(doc_id: str) -> str:
            if "/" in doc_id:
                return doc_id.split("/", 1)[0]
            return doc_id or "[none]"

        prefix_counts: Dict[str, int] = {}
        for doc_id in doc_to_chunks.keys():
            p = _doc_prefix(doc_id)
            prefix_counts[p] = prefix_counts.get(p, 0) + 1
        logger.info(
            f"[Pass1-Doc] '{table_name}': {n_docs} docs, extracting '{identity_col}' "
            f"(fixed-cost summary + contrastive gate + top1, {MAX_PARALLEL_REQUESTS} workers)"
        )
        logger.info(
            f"[Pass1-Doc] '{table_name}' candidate source prefixes: {prefix_counts}"
        )

        sys_prompt = (
            "You are a JSON-only extraction assistant. "
            "Return strict JSON only; no markdown, no explanations."
        )

        # Contrastive relevance gate: force the model to choose among peer
        # tables, not just answer yes/no in isolation. This greatly reduces
        # cross-table contamination when attributes overlap (e.g. nationality).
        all_tables = []
        try:
            all_tables = sorted(list(self.lattice_planner.lattice.tables.keys()))
        except Exception:
            all_tables = []
        if table_name not in all_tables:
            all_tables.append(table_name)
        allowed_tables = [t.lower() for t in all_tables] + ["none"]
        allowed_table_set = set(allowed_tables)
        table_choices = ", ".join(allowed_tables)
        relevance_prompt = (
            f'Classify which table this document is primarily about.\n'
            f'Allowed tables: [{table_choices}].\n'
            'Return ONLY one token from the allowed tables. No JSON.\n\n'
            'Document:\n---\n__DOCUMENT__\n---'
        )
        pass1a_tmpl = (
            f'The following document is about a record in the "{table_name}" table.\n'
            f'Extract the value of the "{identity_col}" column for that record.\n'
            f'Output ONLY a raw JSON array of strings.\n'
            f'No other text.\n\nDocument:\n---\n{{document}}\n---\n["'
        )
        pass1b_tmpl = (
            f'From the following text, extract the value of the "{identity_col}" '
            f'column for a "{table_name}" record.\n'
            f'Output ONLY a raw JSON array of strings.\n'
            f'No other text.\n\nText:\n---\n{{summary}}\n---\n["'
        )

        def _norm(s: str) -> str:
            s = str(s or "").strip().lower()
            s = _re.sub(r"[^\w\s]", " ", s)
            return " ".join(s.split())

        def _parse_json_array(text: str):
            """Extract first non-empty JSON array from text."""
            for raw in ('["' + text.strip(), text.strip()):
                try:
                    val = json.loads(raw)
                    if isinstance(val, list) and val:
                        return val
                except json.JSONDecodeError:
                    pass
            match = _re.search(r"\[.*?\]", '["' + text, _re.DOTALL)
            if match:
                try:
                    val = json.loads(match.group())
                    if isinstance(val, list) and val:
                        return val
                except json.JSONDecodeError:
                    pass
            return None

        def _parse_relevance(text: str) -> Optional[str]:
            """
            Parse table classification token from model output.
            Output must be one allowed table token; any other value is treated
            as invalid/none.
            """
            raw = text.strip()
            m = _re.search(r"[A-Za-z_][A-Za-z0-9_]*", raw)
            if not m:
                return None
            tok = m.group(0).strip().lower()
            return tok if tok in allowed_table_set else None

        def _build_summary(doc_text: str) -> str:
            """
            Build fixed-cost extractive summary for table disambiguation.
            Uses existing bi-encoder + cross-encoder models already loaded in
            entity_resolver. Falls back to head-truncation on any error.
            """
            SUMMARY_CHAR_BUDGET = 3500
            MAX_SENTENCES = 12
            PRESELECT = 40
            LEAD_LINES = 10

            text = (doc_text or "").strip()
            if not text:
                return ""

            # Keep opening lines explicitly (many docs place the key entity in
            # the first few lines) and then add retrieved evidence sentences.
            lead_lines = [ln.strip() for ln in text.splitlines() if ln.strip()][:LEAD_LINES]
            lead_text = "\n".join(lead_lines)

            # Split into sentence-like units.
            parts = []
            for para in text.split("\n"):
                para = para.strip()
                if not para:
                    continue
                parts.extend([s.strip() for s in _re.split(r"(?<=[\.\!\?])\s+", para) if s.strip()])
            if not parts:
                return text[:SUMMARY_CHAR_BUDGET]

            # Use table schema terms as the query for extractive retrieval.
            schema_cols = list(self.lattice_planner.get_table_schema(table_name).keys())
            query_terms = [table_name, identity_col] + schema_cols[:12] + (predicate_hints or [])[:8]
            query = " ".join(t for t in query_terms if t)

            try:
                # Stage 1: bi-encoder preselection
                q_emb = self.entity_resolver.bi_encoder.encode([query], normalize_embeddings=True)
                s_emb = self.entity_resolver.bi_encoder.encode(parts, normalize_embeddings=True)
                # cosine for normalized embeddings = dot product
                sims = (s_emb @ q_emb[0]).tolist()
                top_idx = sorted(range(len(parts)), key=lambda i: sims[i], reverse=True)[: min(PRESELECT, len(parts))]

                # Stage 2: cross-encoder rerank
                pairs = [(query, parts[i]) for i in top_idx]
                scores = self.entity_resolver.cross_encoder.predict(pairs)
                ranked = sorted(zip(top_idx, scores), key=lambda x: float(x[1]), reverse=True)[: min(MAX_SENTENCES, len(top_idx))]

                # Preserve document order in final summary.
                chosen = [parts[i] for i, _ in sorted(ranked, key=lambda x: x[0])]
                # Merge opening lines + retrieved sentences with dedup.
                merged = []
                seen = set()
                for s in lead_lines + chosen:
                    key = _norm(s)
                    if not key or key in seen:
                        continue
                    seen.add(key)
                    merged.append(s)
                summary = "\n".join(merged)
                return summary[:SUMMARY_CHAR_BUDGET] if summary else text[:SUMMARY_CHAR_BUDGET]
            except Exception:
                # Deterministic fallback: first characters only.
                return lead_text[:SUMMARY_CHAR_BUDGET] if lead_text else text[:SUMMARY_CHAR_BUDGET]

        def _is_valid_identity(value: str, doc_text: str) -> bool:
            """Accept only plausible identities grounded in document text."""
            v = (value or "").strip()
            if not v:
                return False
            # Filter obvious placeholders/noise.
            if _norm(v) in {"name", "id", "label", "title", "unknown", "none", "null", "n a"}:
                return False
            if len(v) < 2:
                return False
            if _re.fullmatch(r"\d+", v):
                return False
            # Grounding check: exact or normalized containment.
            if v.lower() in doc_text.lower():
                return True
            return _norm(v) in _norm(doc_text)

        def _discover_entity(doc_id: str) -> Tuple[Optional[str], str, Optional[str]]:
            """
            Return (entity, reason, best_table_seen).
            reason ∈ {"accepted", "irrelevant", "other_table", "unparseable", "invalid", "read_error"}
            """
            doc_path = dataset_path / doc_id
            try:
                doc_text = doc_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                logger.warning(f"[Pass1-Doc] Cannot read {doc_path}")
                return None, "read_error", None

            summary_text = _build_summary(doc_text)

            # 1) Relevance gate (table-level) on summary only.
            try:
                rel_resp = self.llm_client.generate(
                    relevance_prompt.replace("__DOCUMENT__", summary_text),
                    max_tokens=48,
                    temperature=0.0,
                    system_prompt=sys_prompt,
                )
                best_table = _parse_relevance(rel_resp)
            except Exception as exc:
                logger.warning(f"[Pass1-Doc] Relevance call error for {doc_id}: {exc}")
                return None, "unparseable", None

            if best_table in (None, "none"):
                return None, "irrelevant", best_table
            if best_table != table_name.lower():
                return None, "other_table", best_table

            # 2) Identity extraction (top-1) on summary only.
            resp_a = ""
            try:
                resp_a = self.llm_client.generate(
                    pass1a_tmpl.format(document=summary_text),
                    max_tokens=128,
                    temperature=0.0,
                    system_prompt=sys_prompt,
                )
                entities = _parse_json_array(resp_a)
                if entities:
                    entity = str(entities[0]).strip()
                    if _is_valid_identity(entity, summary_text):
                        return entity, "accepted", best_table
            except Exception as exc:
                logger.warning(f"[Pass1-Doc] Pass 1a error for {doc_id}: {exc}")

            # 3) Pass 1b fallback from prose response.
            if resp_a.strip():
                try:
                    resp_b = self.llm_client.generate(
                        pass1b_tmpl.format(summary=resp_a),
                        max_tokens=128,
                        temperature=0.0,
                        system_prompt=sys_prompt,
                    )
                    entities = _parse_json_array(resp_b)
                    if entities:
                        entity = str(entities[0]).strip()
                        if _is_valid_identity(entity, summary_text):
                            return entity, "accepted", best_table
                except Exception as exc:
                    logger.warning(f"[Pass1-Doc] Pass 1b error for {doc_id}: {exc}")

            return None, "invalid", best_table

        raw: Dict[str, List[str]] = {}
        assigned_chunk_ids: set = set()
        rejected_docs: Dict[str, str] = {}
        rejected_best_table: Dict[str, Optional[str]] = {}
        accepted_docs: Dict[str, str] = {}
        done = 0

        with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as pool:
            fut_to_doc = {
                pool.submit(_discover_entity, doc_id): doc_id
                for doc_id in doc_to_chunks
            }
            for fut in _asc(fut_to_doc):
                doc_id = fut_to_doc[fut]
                done += 1
                if done % 100 == 0 or done == n_docs:
                    logger.info(f"[Pass1-Doc] {done}/{n_docs} docs processed")

                entity_name, reason, best_table = fut.result()
                if entity_name:
                    cids = [c.chunk_id for c in doc_to_chunks[doc_id]]
                    raw.setdefault(entity_name, []).extend(cids)
                    assigned_chunk_ids.update(cids)
                    accepted_docs[doc_id] = entity_name
                else:
                    rejected_docs[doc_id] = reason
                    rejected_best_table[doc_id] = best_table

        reason_counts: Dict[str, int] = {}
        for r in rejected_docs.values():
            reason_counts[r] = reason_counts.get(r, 0) + 1
        accepted_prefix_counts: Dict[str, int] = {}
        for doc_id in accepted_docs.keys():
            p = _doc_prefix(doc_id)
            accepted_prefix_counts[p] = accepted_prefix_counts.get(p, 0) + 1

        misclass_counts: Dict[str, int] = {}
        misclass_examples: List[str] = []
        for doc_id, reason in rejected_docs.items():
            if reason != "other_table":
                continue
            bt = (rejected_best_table.get(doc_id) or "[none]").lower()
            misclass_counts[bt] = misclass_counts.get(bt, 0) + 1
            if len(misclass_examples) < 12:
                misclass_examples.append(f"{doc_id} -> {bt}")

        if rejected_docs:
            logger.info(
                f"[Pass1-Doc] Rejected docs: {len(rejected_docs)}/{n_docs}; "
                f"reasons={reason_counts}. No fallback in fixed-cost mode."
            )
            if misclass_counts:
                logger.info(
                    f"[Pass1-Doc] '{table_name}' misclassified-to tables: {misclass_counts}"
                )
                logger.info(
                    f"[Pass1-Doc] '{table_name}' misclassification samples: {misclass_examples}"
                )
        logger.info(
            f"[Pass1-Doc] '{table_name}' accepted doc source prefixes: {accepted_prefix_counts}"
        )

        # Deduplicate chunk lists per entity.
        for entity, cids in raw.items():
            raw[entity] = list(dict.fromkeys(cids))

        non_null = sum(len(v) for v in raw.values())
        logger.info(
            f"[Pass1-Doc] Done: {len(raw)} raw entity values, "
            f"{non_null}/{len(candidate_chunks)} chunks attributed"
        )
        return raw

    def _group_chunks_by_entity(
        self,
        candidate_chunks: list,
        ner_label: Optional[str],
        top_k_per_entity: int,
        table_name: str = "",
        identity_col: str = "",
        schema: Optional[Dict] = None,
        pass1_raw: Optional[Dict[str, List[str]]] = None,
    ) -> tuple:
        """
        Two-phase entity grouping driven by Pass 1 extraction results.

        Pass 1 (done before this call) already extracted raw identity-column
        values from every candidate chunk.  This method:

        1. Runs entity resolution (bi-encoder blocking + cross-encoder matching)
           on the raw Pass 1 values to collapse variants into canonical entities.
           "Beazley", "Beazley plc", "BEAZLEYPLC" → "Beazley plc".
           "COVID-19", "SARS-CoV-2" → "COVID-19".

        2. Builds the entity → [TextChunk] mapping directly from the chunk_ids
           recorded during Pass 1.  No keyword matching, no NER, no top-K.
           Every chunk that mentioned a variant of an entity is assigned to it.

        Returns:
            entity_to_chunks : Dict[str, List[TextChunk]] — chunks per canonical entity
            unassigned       : List[TextChunk] — chunks with no Pass 1 match
        """
        from collections import defaultdict

        if not pass1_raw:
            logger.warning(
                "[GroupChunks] No Pass 1 results — all chunks unassigned"
            )
            return {}, candidate_chunks

        # Build chunk_id → TextChunk lookup for fast resolution.
        chunk_lookup: Dict[str, object] = {c.chunk_id: c for c in candidate_chunks}
        assigned_ids: set = set()

        # ── Entity resolution on raw Pass 1 values ───────────────────────────
        from entity_resolver import EntityMention
        mentions = [
            EntityMention(
                mention_id=f"{table_name}_{identity_col}_{val}",
                value=val,
                table_name=table_name,
                column_name=identity_col,
                semantic_type="ORG",
            )
            for val in pass1_raw.keys()
            if val and val.strip()
        ]

        canonical_map: Dict[str, str] = {}   # raw_value → canonical
        if len(mentions) >= 2:
            try:
                result = self.entity_resolver.resolve_entities(mentions)
                canonical_map = result.canonical_map   # raw_val → canonical
                logger.info(
                    f"[GroupChunks] Entity resolution: {len(pass1_raw)} raw values → "
                    f"{result.total_clusters} canonical entities"
                )
            except Exception as exc:
                logger.warning(f"[GroupChunks] Entity resolution failed: {exc}. "
                               "Treating each raw value as its own canonical.")
        # Fallback: identity mapping
        for val in pass1_raw:
            if val not in canonical_map:
                canonical_map[val] = val

        # ── Build entity → [TextChunk] from Pass 1 chunk_ids ─────────────────
        entity_to_chunks: Dict[str, list] = defaultdict(list)
        for raw_val, chunk_ids in pass1_raw.items():
            canon = canonical_map.get(raw_val, raw_val)
            for cid in chunk_ids:
                chunk = chunk_lookup.get(cid)
                if chunk:
                    entity_to_chunks[canon].append(chunk)
                    assigned_ids.add(cid)

        unassigned = [c for c in candidate_chunks if c.chunk_id not in assigned_ids]

        logger.info(
            f"[GroupChunks] {len(entity_to_chunks)} canonical entities, "
            f"{sum(len(v) for v in entity_to_chunks.values())} assigned chunks, "
            f"{len(unassigned)} unassigned"
        )
        return dict(entity_to_chunks), unassigned

    def _entity_first_extraction(
        self,
        table_name: str,
        schema: Dict[str, Any],
        sql_schema: Dict[str, Any],
        identity_col: str,
        ner_label: Optional[str],
        candidate_chunks: list,
        normalization_hints: Dict[str, Any],
        pass1_raw: Optional[Dict[str, List[str]]] = None,
    ) -> int:
        """
        Entity-first extraction pipeline.

        1. Run Pass 1 (identity-col-only, all chunks, parallel) to get
           raw entity values and the chunk_ids that mention them.
        2. Entity resolution collapses raw variants into canonical entities
           and maps each chunk to its canonical.
        3. For each canonical entity, run full schema extraction on only
           its linked chunks — no top-K gate, no NER, no sampling bias.
        4. Stamp identity_col unconditionally with the canonical entity name
           to prevent LLM hallucination on that column.
        5. Process unassigned chunks (no entity mention found) with the
           brute-force path, capped by UNASSIGNED_CHUNK_CAP.

        LLM calls ≈ N_entities × avg_chunks_per_entity (Pass 2)
                  + N_candidate_chunks (Pass 1, cheap single-column calls)
        """
        from config import TOP_K_CHUNKS_PER_ENTITY, UNASSIGNED_CHUNK_CAP

        entity_to_chunks, unassigned = self._group_chunks_by_entity(
            candidate_chunks, ner_label,
            top_k_per_entity=TOP_K_CHUNKS_PER_ENTITY,
            table_name=table_name,
            identity_col=identity_col,
            schema=schema,
            pass1_raw=pass1_raw,
        )

        # For entity-first extraction the context is tightly focused (all
        # chunks belong to ONE entity), so the 7B model can reliably handle
        # the full schema in a single call.  Pass col_batch_size_override that
        # exceeds schema width to disable column batching entirely.
        _no_batch_size = len(schema) + 1

        self.data_layer.create_dynamic_table(table_name, sql_schema)
        total_records = 0

        # --- Per-entity targeted LLM extraction (parallel) ---
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from config import EXTRACTION_MAX_WORKERS

        entity_items = list(entity_to_chunks.items())
        logger.info(
            f"[EntityFirst] Extracting {len(entity_items)} entities × "
            f"≤{TOP_K_CHUNKS_PER_ENTITY} chunks each for '{table_name}' "
            f"using {EXTRACTION_MAX_WORKERS} workers"
        )

        def _extract_entity(entity_name: str, entity_chunks: list):
            chunk_texts   = [c.content  for c in entity_chunks]
            chunk_ids_lst = [c.chunk_id for c in entity_chunks]
            # Map chunk_id → doc_id so we can populate cell provenance.
            chunk_doc_map = {c.chunk_id: c.doc_id for c in entity_chunks}
            results = self.extractor.extract_batch(
                chunk_texts,
                chunk_ids_lst,
                table_name,
                schema,
                normalization_hints=normalization_hints,
                entity_col=identity_col,
                col_batch_size_override=_no_batch_size,
            )
            triples = []
            for er in results:
                if er.error:
                    continue
                doc_id = chunk_doc_map.get(er.chunk_id, "")
                local_texts = [
                    c.content for c in entity_chunks
                    if c.chunk_id == er.chunk_id
                ]
                for rec_idx, record in enumerate(er.records):
                    # Stamp identity unconditionally (prevent LLM override).
                    record["_entity"] = entity_name
                    record[identity_col] = entity_name
                    # Retrieve the per-column spans returned alongside values.
                    rec_spans = (
                        er.spans[rec_idx]
                        if er.spans and rec_idx < len(er.spans)
                        else None
                    )
                    # Type check + span-grounding validation on all other cols.
                    record = _validate_record(
                        record, sql_schema, local_texts, identity_col, rec_spans
                    )
                    triples.append((record, er.chunk_id, doc_id))
            return triples

        # Collect all results then bulk-upsert once per 1000 entities to
        # amortise the DB round-trips without holding everything in RAM.
        all_triples: list = []
        batch_size = 1000

        with ThreadPoolExecutor(max_workers=EXTRACTION_MAX_WORKERS) as pool:
            futs = {
                pool.submit(_extract_entity, name, chunks): name
                for name, chunks in entity_items
            }
            done_count = 0
            for fut in as_completed(futs):
                all_triples.extend(fut.result())
                done_count += 1
                if done_count % batch_size == 0:
                    if all_triples:
                        row_pv, cell_pv = self.data_layer.upsert_by_entity(
                            table_name, identity_col, all_triples
                        )
                        self.data_layer.bulk_insert_provenance(table_name, row_pv)
                        self.data_layer.bulk_insert_cell_provenance(cell_pv)
                        total_records += len(row_pv)
                        all_triples = []
                    logger.info(f"[EntityFirst] {done_count}/{len(entity_items)} entities done")

        # Flush remainder
        if all_triples:
            row_pv, cell_pv = self.data_layer.upsert_by_entity(
                table_name, identity_col, all_triples
            )
            self.data_layer.bulk_insert_provenance(table_name, row_pv)
            self.data_layer.bulk_insert_cell_provenance(cell_pv)
            total_records += len(row_pv)

        # --- Unassigned chunks: hard-capped standard extraction ──────────────
        # Unassigned = chunks where Pass 1 found no entity mention.  A hard cap
        # prevents this from becoming a bottleneck in pathological cases.
        if unassigned and UNASSIGNED_CHUNK_CAP > 0:
            to_process = unassigned[:UNASSIGNED_CHUNK_CAP]
            logger.info(
                f"[EntityFirst] Processing {len(to_process)} unassigned chunks "
                f"(hard cap={UNASSIGNED_CHUNK_CAP}, total unassigned={len(unassigned)})"
            )
            ua_texts = [c.content for c in to_process]
            ua_ids   = [c.chunk_id for c in to_process]
            ua_doc_map = {c.chunk_id: c.doc_id for c in to_process}
            results  = self.extractor.extract_batch(
                ua_texts, ua_ids, table_name, schema,
                normalization_hints=normalization_hints,
                entity_col=identity_col,
                col_batch_size_override=_no_batch_size,
            )
            ua_triples = []
            for er in results:
                if er.error:
                    continue
                doc_id = ua_doc_map.get(er.chunk_id, "")
                local_texts = [c.content for c in to_process if c.chunk_id == er.chunk_id]
                for rec_idx, record in enumerate(er.records):
                    rec_spans = (
                        er.spans[rec_idx]
                        if er.spans and rec_idx < len(er.spans)
                        else None
                    )
                    record = _validate_record(
                        record, sql_schema, local_texts, identity_col, rec_spans
                    )
                    ua_triples.append((record, er.chunk_id, doc_id))
            if ua_triples:
                row_pv, cell_pv = self.data_layer.upsert_by_entity(
                    table_name, identity_col, ua_triples
                )
                self.data_layer.bulk_insert_provenance(table_name, row_pv)
                self.data_layer.bulk_insert_cell_provenance(cell_pv)
                total_records += len(row_pv)
        elif unassigned:
            logger.info(
                f"[EntityFirst] Skipping {len(unassigned)} unassigned chunks "
                f"(UNASSIGNED_CHUNK_CAP={UNASSIGNED_CHUNK_CAP})."
            )

        return total_records

    def _preflight_check(self, lattice, dataset_path: Path) -> None:
        """
        Comprehensive pre-flight validation executed BEFORE any LLM extraction.

        Checks (in order):
          1. Required config variables are importable and have valid values.
          2. Source data directory exists and contains at least one text file.
          3. Ollama LLM is reachable and returns a well-formed response.
          4. Entity resolver models (bi-encoder, cross-encoder) are loaded.
          5. DB is writable (scratch INSERT/DELETE to a temp row).
          6. Per-table: identity column is a real workload column (not virtual).
          7. Per-table: if the table already exists in the DB, its column set is
             a superset of what the workload schema requires; missing columns are
             added via ALTER TABLE so IF NOT EXISTS never silently omits them.
          8. Per-table: candidate chunk count — warn when zero.

        Raises RuntimeError on any hard failure so the run aborts immediately
        instead of hours later.
        """
        failures: List[str] = []

        # ── 1. Config variable imports ────────────────────────────────────────
        logger.info("[PreFlight] 1/8 Checking config variables…")
        _required_config_vars = [
            "EXTRACTION_MAX_WORKERS",
            "NER_BATCH_SIZE",
            "UNASSIGNED_CHUNK_CAP",
            "TOP_K_CHUNKS_PER_ENTITY",
            "CHUNK_BATCH_SIZE",
            "COLUMN_BATCH_SIZE",
            "OLLAMA_URL",
            "OLLAMA_MODEL",
            "BI_ENCODER_MODEL",
            "CROSS_ENCODER_MODEL",
            "MAX_PARALLEL_REQUESTS",
        ]
        import config as _cfg
        for var in _required_config_vars:
            if not hasattr(_cfg, var):
                failures.append(f"config.{var} is missing")
            elif getattr(_cfg, var) is None:
                failures.append(f"config.{var} is None")

        # ── 2. Source data directory ──────────────────────────────────────────
        logger.info("[PreFlight] 2/8 Checking source data…")
        if not dataset_path.exists():
            failures.append(
                f"Source data directory does not exist: {dataset_path}"
            )
        else:
            txt_files = list(dataset_path.rglob("*.txt"))
            if not txt_files:
                failures.append(
                    f"No .txt files found under {dataset_path}. "
                    f"Nothing to ingest."
                )
            else:
                logger.info(
                    f"[PreFlight] Source data OK: {len(txt_files)} .txt files"
                )

        # ── 3. LLM connectivity ───────────────────────────────────────────────
        logger.info("[PreFlight] 3/8 Checking Ollama connectivity…")
        try:
            probe = self.llm_client.generate(
                "Reply with the single word: OK", max_tokens=5, temperature=0.0
            )
            if not isinstance(probe, str) or not probe.strip():
                failures.append(
                    f"Ollama returned an empty or non-string response: {probe!r}"
                )
            else:
                logger.info(f"[PreFlight] Ollama OK (probe response: {probe.strip()!r})")
        except Exception as exc:
            failures.append(f"Ollama unreachable: {exc}")

        # ── 4. Entity resolver models ─────────────────────────────────────────
        logger.info("[PreFlight] 4/8 Checking entity resolver models…")
        try:
            # Accessing the model attributes forces lazy-load if not yet done.
            _ = self.entity_resolver.bi_encoder
            _ = self.entity_resolver.cross_encoder
            logger.info("[PreFlight] Entity resolver models OK")
        except Exception as exc:
            failures.append(f"Entity resolver model load failed: {exc}")

        # ── 5. DB write permission ────────────────────────────────────────────
        logger.info("[PreFlight] 5/8 Checking DB writability…")
        try:
            _PROBE_TABLE = "_preflight_probe"
            with self.data_layer.engine.connect() as _conn:
                _conn.execute(_sa_text(
                    f"CREATE TABLE IF NOT EXISTS {_PROBE_TABLE} "
                    f"(id TEXT PRIMARY KEY)"
                ))
                _conn.execute(_sa_text(
                    f"INSERT OR IGNORE INTO {_PROBE_TABLE} (id) VALUES ('ok')"
                ))
                _conn.execute(_sa_text(f"DROP TABLE IF EXISTS {_PROBE_TABLE}"))
                _conn.commit()
            logger.info("[PreFlight] DB write test OK")
        except Exception as exc:
            failures.append(f"DB write test failed: {exc}")

        # ── 6. Identity column vs workload schema ─────────────────────────────
        logger.info("[PreFlight] 6/8 Checking identity columns vs schema…")
        for table_name in lattice.tables:
            table_info = lattice.tables[table_name]
            identity_col = self.identity_columns.get(table_name)
            # The identity column may be absent from the queried schema (the
            # shim injects it during extraction).  Validate it exists in
            # table_info.columns (i.e. it is a real column the lattice knows
            # about) rather than just in the narrow query SELECT list.
            if identity_col is not None and identity_col not in table_info.columns:
                failures.append(
                    f"Table '{table_name}': identity column '{identity_col}' "
                    f"is not a known table column "
                    f"(known={list(table_info.columns.keys())}). "
                    f"This would cause a column-not-found error during extraction."
                )

        # ── 7. Existing table schema compatibility ────────────────────────────
        logger.info("[PreFlight] 7/8 Checking existing DB table schemas…")
        try:
            for table_name, _tinfo in lattice.tables.items():
                schema = self.lattice_planner.get_table_schema(table_name)
                sql_schema = {
                    col: semantic_to_sql_type(sem)
                    for col, sem in schema.items()
                }
                with self.data_layer.engine.connect() as _conn:
                    existing_rows = _conn.execute(
                        _sa_text(f"PRAGMA table_info({table_name})")
                    ).fetchall()
                if not existing_rows:
                    # Table doesn't exist yet — will be created during extraction.
                    continue
                existing_cols = {r[1] for r in existing_rows}
                missing = set(sql_schema.keys()) - existing_cols
                if missing:
                    logger.warning(
                        f"[PreFlight] Table '{table_name}' exists but is missing "
                        f"columns {missing}. Adding via ALTER TABLE…"
                    )
                    with self.data_layer.engine.connect() as _conn:
                        for col in missing:
                            col_type = sql_schema[col]
                            try:
                                _conn.execute(_sa_text(
                                    f"ALTER TABLE {table_name} "
                                    f"ADD COLUMN {col} {col_type}"
                                ))
                                logger.info(
                                    f"[PreFlight] Added column '{col}' "
                                    f"({col_type}) to '{table_name}'"
                                )
                            except Exception as alter_exc:
                                failures.append(
                                    f"ALTER TABLE {table_name} ADD COLUMN "
                                    f"{col}: {alter_exc}"
                                )
                        _conn.commit()
        except Exception as exc:
            failures.append(f"Table schema compatibility check failed: {exc}")

        # ── 8. Candidate chunk counts ─────────────────────────────────────────
        logger.info("[PreFlight] 8/8 Checking candidate chunk counts…")
        for table_name in lattice.tables:
            count = len(self.data_layer.get_candidates(table_name))
            if count == 0:
                logger.warning(
                    f"[PreFlight] Table '{table_name}' has 0 candidate chunks. "
                    f"The sieve may have filtered everything out, or ingestion "
                    f"has not run yet. This table will produce no extracted rows."
                )
            else:
                logger.info(
                    f"[PreFlight] Table '{table_name}': {count} candidate chunks"
                )

        # ── Final verdict ─────────────────────────────────────────────────────
        if failures:
            msg = "\n".join(f"  • {f}" for f in failures)
            raise RuntimeError(
                f"[PreFlight] {len(failures)} check(s) failed — "
                f"aborting before extraction:\n{msg}"
            )

        logger.info("[PreFlight] All 8 checks passed. Starting extraction.")

    def _load_table_source_documents(
        self,
        dataset_path: Path,
        table_name: str,
    ) -> Tuple[List[str], List[str]]:
        """
        Load raw source documents for a table from source_data/<dataset>/<table_name>/*.txt.
        Returns (texts, synthetic_chunk_ids) for projection fast-path extraction.
        """
        table_dir = dataset_path / table_name
        if not table_dir.exists():
            return [], []

        doc_files = sorted(table_dir.glob("*.txt"), key=lambda p: p.stem)
        texts: List[str] = []
        chunk_ids: List[str] = []
        for p in doc_files:
            try:
                txt = p.read_text(errors="ignore")
            except Exception:
                continue
            if not txt.strip():
                continue
            texts.append(txt)
            chunk_ids.append(f"doc::{table_name}::{p.stem}")
        return texts, chunk_ids

    def _global_extraction(self, lattice) -> int:
        """Perform predicate-based extraction (like QAIRS)."""
        total_records = 0

        # Validate before spending any time on LLM calls.
        dataset_path = get_dataset_path(self.dataset)
        self._preflight_check(lattice, dataset_path)
        
        # Check if there are joins in the workload
        has_joins = len(lattice.join_pairs) > 0
        if has_joins:
            logger.info(f"Workload has {len(lattice.join_pairs)} join pairs: {lattice.join_pairs}")
            for lt, lc, rt, rc in getattr(lattice, "join_column_pairs", []):
                logger.info(f"  Join ON: {lt}.{lc} = {rt}.{rc}")
        
        for table_name, table_info in lattice.tables.items():
            try:
                # Get schema
                schema = self.lattice_planner.get_table_schema(table_name)
                
                # Convert semantic types to SQL types for table creation
                sql_schema = {col: semantic_to_sql_type(sem_type) 
                             for col, sem_type in schema.items()}

                # Build normalization hints from workload predicate literals so the
                # LLM stores values in the exact form the queries expect
                # (e.g. "USA" not "United States" if queries filter on 'USA').
                normalization_hints = self.lattice_planner.get_normalization_hints(table_name)
                if normalization_hints:
                    logger.info(
                        f"Normalization hints for {table_name}: "
                        + ", ".join(f"{c}={v}" for c, v in normalization_hints.items())
                    )

                # For tables in joins, extract ALL data to ensure referential integrity
                # Phase 2 will handle join alignment
                entity_col = self.identity_columns.get(table_name)

                # ── Identity-column shim ─────────────────────────────────────
                # If the identity column was detected but isn't in this query's
                # SELECT list (e.g. "SELECT earnings_per_share FROM finance"
                # omits company_name), inject it into the extraction schema now.
                # The entity-first path needs it as an anchor; the original SQL
                # runs against SQLite later and is never modified, so the extra
                # column has zero effect on the final query results.
                if entity_col and entity_col not in schema:
                    col_info = table_info.columns.get(entity_col)
                    sem_type = (
                        getattr(col_info, "semantic_type", "ORG")
                        if col_info else "ORG"
                    )
                    schema[entity_col] = sem_type
                    sql_schema[entity_col] = "TEXT"
                    logger.info(
                        f"[IdentityShim] Injected '{entity_col}' into extraction "
                        f"schema for '{table_name}' (not in query SELECT list)"
                    )

                # ── Projection fast path: source docs -> inferred columns only ──
                if self.use_projection_fastpath:
                    source_texts, source_ids = self._load_table_source_documents(
                        dataset_path, table_name
                    )
                    if source_texts:
                        logger.info(
                            f"[ProjectionFastPath] {table_name}: {len(source_texts)} source docs, "
                            f"{len(schema)} inferred columns"
                        )
                        sample_chunks = source_texts[:50]
                        stabilized_schema = self.extractor.stabilize_schema(
                            table_name,
                            schema,
                            sample_chunks,
                        )
                        self.data_layer.create_dynamic_table(table_name, sql_schema)

                        col_batch_override = (
                            self.projection_fastpath_col_batch_size
                            if self.projection_fastpath_col_batch_size > 0
                            else max(1, len(schema))
                        )
                        results = self.extractor.extract_batch(
                            source_texts,
                            source_ids,
                            table_name,
                            schema,
                            stabilized_schema.frozen_keys,
                            normalization_hints,
                            # Projection fast path uses plain INSERTs (no upsert-by-entity),
                            # so forcing `_entity` in extraction output only adds a brittle
                            # constraint and can suppress valid rows.
                            entity_col=None,
                            col_batch_size_override=col_batch_override,
                        )

                        table_records = sum(len(r.records) for r in results)
                        total_records += table_records
                        prov_pairs = self.data_layer.bulk_insert_records(table_name, results)
                        self.data_layer.bulk_insert_provenance(table_name, prov_pairs)
                        logger.info(
                            f"[ProjectionFastPath] {table_name}: extracted {table_records} rows "
                            f"from {len(source_texts)} source docs"
                        )
                        
                        # ── Attribute Discovery for Smart Column Delta ──────────────
                        # NOTE: Projection fastpath uses synthetic chunk IDs (doc::table::name),
                        # but Phase 2 delta engine uses actual chunk IDs from the chunk store.
                        # We need to discover attributes from the CHUNKED versions.
                        logger.info(f"[AttributeIndex] Discovering attributes for {table_name}...")
                        candidate_chunk_ids = self.data_layer.get_candidates(table_name)
                        if candidate_chunk_ids:
                            from concurrent.futures import ThreadPoolExecutor, as_completed
                            from config import MAX_PARALLEL_REQUESTS
                            from attribute_index import AttributeDiscovery
                            
                            candidate_chunks = self.data_layer.get_chunks_by_ids(candidate_chunk_ids)
                            logger.info(
                                f"[AttributeIndex] Processing {len(candidate_chunks)} chunks "
                                f"for {table_name} with {MAX_PARALLEL_REQUESTS} workers..."
                            )
                            
                            def _discover_chunk(chunk):
                                attrs = self.extractor.discover_attributes_from_chunk(
                                    chunk.content, chunk.chunk_id, table_name
                                )
                                return (chunk.chunk_id, attrs) if attrs else None
                            
                            discoveries = []
                            with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as executor:
                                futures = {executor.submit(_discover_chunk, c): c for c in candidate_chunks}
                                completed = 0
                                for future in as_completed(futures):
                                    completed += 1
                                    if completed % 500 == 0:
                                        logger.info(f"  [AttributeIndex] {completed}/{len(candidate_chunks)} chunks processed")
                                    try:
                                        result = future.result()
                                        if result:
                                            chunk_id, attrs = result
                                            discovery = AttributeDiscovery(
                                                chunk_id=chunk_id,
                                                table_name=table_name,
                                                discovered_attributes=attrs
                                            )
                                            discoveries.append(discovery)
                                    except Exception as e:
                                        logger.warning(f"[AttributeIndex] Error discovering attributes: {e}")
                            
                            # Add all discoveries to index
                            for discovery in discoveries:
                                self.extractor.attribute_index.add_discovery(discovery)
                            
                            # Log coverage stats
                            coverage = self.extractor.attribute_index.get_coverage_stats(table_name)
                            logger.info(
                                f"[AttributeIndex] {table_name}: discovered {len(coverage)} unique attributes "
                                f"from {len(discoveries)} chunks, coverage: {dict(list(coverage.items())[:5])}"
                            )
                        else:
                            logger.warning(f"[AttributeIndex] No candidate chunks found for {table_name}, skipping attribute discovery")

                        for col_name in schema.keys():
                            self.data_layer.update_metadata(
                                table_name, col_name, [], "FULL", table_records
                            )
                        continue
                    else:
                        logger.warning(
                            f"[ProjectionFastPath] No source docs found for '{table_name}', "
                            "falling back to chunk-based extraction."
                        )
                
                # Get candidate chunks
                candidate_chunk_ids = self.data_layer.get_candidates(table_name)
                
                if not candidate_chunk_ids:
                    logger.warning(f"No candidate chunks for {table_name}")
                    continue
                
                logger.info(f"Table {table_name}: {len(candidate_chunk_ids)} candidates, "
                           f"{len(table_info.predicates)} predicates, "
                           f"in_joins={table_info.referenced_in_joins}")
                
                candidate_chunks = self.data_layer.get_chunks_by_ids(candidate_chunk_ids)
                
                # Schema stabilization
                sample_chunks = [c.content for c in candidate_chunks[:50]]
                stabilized_schema = self.extractor.stabilize_schema(
                    table_name,
                    schema,
                    sample_chunks
                )
                
                logger.info(f"Stabilized schema for {table_name}: "
                           f"{len(stabilized_schema.frozen_keys)} keys")
                
                ner_label = self.identity_ner_labels.get(table_name)

                if entity_col:
                    # ── Pass 1: document-level LLM entity discovery ──────────
                    # One two-pass LLM call per source document (not per chunk).
                    # Each document contains exactly one primary entity, so all
                    # chunks from a document are attributed to the entity
                    # discovered for it.  For Finance (~100 docs) this is ~200
                    # LLM calls total vs 2.4M chunk-level calls in the old path.
                    id_hints = normalization_hints.get(entity_col) or []
                    pass1_raw = self._doc_level_identity_pass(
                        table_name=table_name,
                        identity_col=entity_col,
                        candidate_chunks=candidate_chunks,
                        predicate_hints=id_hints or None,
                        ner_label=ner_label,
                    )

                    # ── Pass 2: full schema extraction on entity-linked chunks ─
                    suffix = "(join table)" if table_info.referenced_in_joins else ""
                    logger.info(
                        f"[EntityFirst] {table_name} {suffix}: "
                        f"Pass1 found {len(pass1_raw)} raw entity values → "
                        f"entity resolution → targeted Pass2 extraction"
                    )
                    table_records = self._entity_first_extraction(
                        table_name=table_name,
                        schema=schema,
                        sql_schema=sql_schema,
                        identity_col=entity_col,
                        ner_label=ner_label,
                        candidate_chunks=candidate_chunks,
                        normalization_hints=normalization_hints,
                        pass1_raw=pass1_raw,
                    )
                    total_records += table_records
                    
                    # ── Attribute Discovery for Smart Column Delta ──────────────
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    from config import MAX_PARALLEL_REQUESTS
                    from attribute_index import AttributeDiscovery
                    
                    logger.info(
                        f"[AttributeIndex] Discovering attributes for {table_name} "
                        f"from {len(candidate_chunks)} chunks with {MAX_PARALLEL_REQUESTS} workers..."
                    )
                    
                    def _discover_chunk(chunk):
                        attrs = self.extractor.discover_attributes_from_chunk(
                            chunk.content, chunk.chunk_id, table_name
                        )
                        return (chunk.chunk_id, attrs) if attrs else None
                    
                    discoveries = []
                    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as executor:
                        futures = {executor.submit(_discover_chunk, c): c for c in candidate_chunks}
                        completed = 0
                        for future in as_completed(futures):
                            completed += 1
                            if completed % 500 == 0:
                                logger.info(f"  [AttributeIndex] {completed}/{len(candidate_chunks)} chunks processed")
                            try:
                                result = future.result()
                                if result:
                                    chunk_id, attrs = result
                                    discovery = AttributeDiscovery(
                                        chunk_id=chunk_id,
                                        table_name=table_name,
                                        discovered_attributes=attrs
                                    )
                                    discoveries.append(discovery)
                            except Exception as e:
                                logger.warning(f"[AttributeIndex] Error discovering attributes: {e}")
                    
                    # Add all discoveries to index
                    for discovery in discoveries:
                        self.extractor.attribute_index.add_discovery(discovery)
                    
                    # Log coverage stats
                    coverage = self.extractor.attribute_index.get_coverage_stats(table_name)
                    logger.info(
                        f"[AttributeIndex] {table_name}: discovered {len(coverage)} unique attributes "
                        f"from {len(discoveries)} chunks, coverage: {dict(list(coverage.items())[:5])}"
                    )
                else:
                    # ── Brute-force extraction (no identity column) ──────────
                    # Only for tables where no entity anchor was found at all.
                    # This is the old path — every candidate chunk is processed.
                    logger.info(
                        f"[BruteForce] {table_name}: "
                        f"{len(candidate_chunks)} candidates, no identity column"
                    )
                    chunk_texts = [c.content for c in candidate_chunks]
                    chunk_ids_list = [c.chunk_id for c in candidate_chunks]

                    results = self.extractor.extract_batch(
                        chunk_texts,
                        chunk_ids_list,
                        table_name,
                        schema,
                        stabilized_schema.frozen_keys,
                        normalization_hints,
                    )

                    table_records = sum(len(r.records) for r in results)
                    total_records += table_records
                    logger.info(f"Extracted {table_records} records for {table_name}")
                    
                    # ── Attribute Discovery for Smart Column Delta ──────────────
                    from concurrent.futures import ThreadPoolExecutor, as_completed
                    from config import MAX_PARALLEL_REQUESTS
                    from attribute_index import AttributeDiscovery
                    
                    logger.info(
                        f"[AttributeIndex] Discovering attributes for {table_name} "
                        f"from {len(chunk_texts)} chunks with {MAX_PARALLEL_REQUESTS} workers..."
                    )
                    
                    def _discover_chunk(chunk_text, chunk_id):
                        attrs = self.extractor.discover_attributes_from_chunk(
                            chunk_text, chunk_id, table_name
                        )
                        return (chunk_id, attrs) if attrs else None
                    
                    discoveries = []
                    with ThreadPoolExecutor(max_workers=MAX_PARALLEL_REQUESTS) as executor:
                        futures = {
                            executor.submit(_discover_chunk, text, cid): cid 
                            for text, cid in zip(chunk_texts, chunk_ids_list)
                        }
                        completed = 0
                        for future in as_completed(futures):
                            completed += 1
                            if completed % 500 == 0:
                                logger.info(f"  [AttributeIndex] {completed}/{len(chunk_texts)} chunks processed")
                            try:
                                result = future.result()
                                if result:
                                    chunk_id, attrs = result
                                    discovery = AttributeDiscovery(
                                        chunk_id=chunk_id,
                                        table_name=table_name,
                                        discovered_attributes=attrs
                                    )
                                    discoveries.append(discovery)
                            except Exception as e:
                                logger.warning(f"[AttributeIndex] Error discovering attributes: {e}")
                    
                    # Add all discoveries to index
                    for discovery in discoveries:
                        self.extractor.attribute_index.add_discovery(discovery)
                    
                    # Log coverage stats
                    coverage = self.extractor.attribute_index.get_coverage_stats(table_name)
                    logger.info(
                        f"[AttributeIndex] {table_name}: discovered {len(coverage)} unique attributes "
                        f"from {len(discoveries)} chunks, coverage: {dict(list(coverage.items())[:5])}"
                    )

                    self.data_layer.create_dynamic_table(table_name, sql_schema)
                    prov_pairs = self.data_layer.bulk_insert_records(table_name, results)
                    self.data_layer.bulk_insert_provenance(table_name, prov_pairs)
                    logger.info(f"Inserted {len(prov_pairs)} records into {table_name}")

                # Mark every column FULL — we extracted everything we could find.
                # Any runtime predicate on these columns is a cache hit.
                for col_name in schema.keys():
                    self.data_layer.update_metadata(
                        table_name, col_name, [], "FULL", table_records
                    )
            
            except Exception as e:
                logger.error(f"Error extracting for {table_name}: {e}")
                raise RuntimeError(f"Extraction failed for table '{table_name}': {e}") from e
        
        return total_records

    # -------------------------------------------------------------------------
    # Step 4.5: Record Consolidation
    # -------------------------------------------------------------------------

    def _get_identity_column_llm(self, table_name: str, columns: List[str]) -> Optional[str]:
        """
        Ask the LLM to identify the single column that is the primary identity
        key for this table (i.e. the column that uniquely names the real-world entity).
        Returns the column name, or None if it cannot be determined.
        """
        prompt = (
            f"You are a database schema expert.\n"
            f"Table name: '{table_name}'\n"
            f"Columns: {columns}\n\n"
            f"Which SINGLE column is the PRIMARY IDENTITY column — the one that uniquely "
            f"identifies a real-world entity in this table "
            f"(e.g. person name, company name, player name, team name)?\n\n"
            f"Rules:\n"
            f"- Respond with ONLY the exact column name from the list above.\n"
            f"- Do NOT include any explanation, punctuation, or extra words.\n"
            f"- If no single column clearly identifies the entity, respond with NULL."
        )
        try:
            response = self.extractor.ollama_client.generate(
                prompt,
                max_tokens=20,
                temperature=0.0
            ).strip().strip('"').strip("'")

            # Validate the response is actually one of the columns
            col_lower = {c.lower(): c for c in columns}
            if response.lower() in col_lower:
                chosen = col_lower[response.lower()]
                logger.info(f"LLM chose identity column for '{table_name}': {chosen}")
                return chosen

            if response.upper() == "NULL":
                logger.warning(f"LLM could not identify an identity column for '{table_name}'")
                return None

            # LLM returned something not in the column list — fail loudly
            raise RuntimeError(
                f"LLM returned invalid identity column '{response}' for table '{table_name}'. "
                f"Valid columns: {columns}"
            )
        except RuntimeError:
            raise
        except Exception as e:
            raise RuntimeError(
                f"LLM call failed while identifying identity column for '{table_name}': {e}"
            ) from e

    def _consolidate_records(self, lattice) -> None:
        """
        Post-extraction consolidation pass (Step 4.5).

        For each synthesized table:
          1. Ask the LLM which column is the identity key.
          2. Group all rows by the lowercase canonical value of that column.
          3. For groups with >1 row, merge using frequency-wins per attribute.
          4. Keep one canonical row, delete the duplicates, and merge provenance.
        """
        from collections import defaultdict, Counter

        for table_name in list(lattice.tables.keys()):
            logger.info(f"[Consolidation] Processing table '{table_name}'...")

            try:
                all_rows = self.data_layer.get_all_records(table_name)
            except Exception as e:
                logger.error(f"[Consolidation] Cannot read records from '{table_name}': {e}")
                raise

            if len(all_rows) <= 1:
                logger.info(f"[Consolidation] '{table_name}' has {len(all_rows)} rows — nothing to consolidate.")
                continue

            # Columns available in this table (excluding system columns)
            system_cols = {"row_id", "created_at"}
            data_columns = [c for c in all_rows[0].keys() if c not in system_cols]

            if not data_columns:
                logger.warning(f"[Consolidation] No data columns in '{table_name}', skipping.")
                continue

            # Use pre-detected identity column (avoids redundant LLM call).
            identity_col = self.identity_columns.get(table_name)
            if identity_col is None:
                logger.warning(
                    f"[Consolidation] No identity column for '{table_name}' — skipping consolidation."
                )
                continue

            # Step 2: Group rows by canonical identity value
            groups: Dict[str, List[Dict]] = defaultdict(list)
            no_identity = []
            for row in all_rows:
                key = str(row.get(identity_col) or "").strip().lower()
                if key:
                    groups[key].append(row)
                else:
                    no_identity.append(row)

            if no_identity:
                logger.warning(
                    f"[Consolidation] {len(no_identity)} rows in '{table_name}' "
                    f"have no identity value — left as-is."
                )

            merged_count = 0
            deleted_count = 0

            for key, rows in groups.items():
                if len(rows) == 1:
                    continue  # already unique

                # Step 3: Merge using frequency-wins
                merged_data: Dict[str, Any] = {}
                for col in data_columns:
                    if col == identity_col:
                        # Keep the most frequent spelling (frequency-wins)
                        spellings = [str(r[col]).strip() for r in rows if r.get(col)]
                        merged_data[col] = Counter(spellings).most_common(1)[0][0] if spellings else None
                    else:
                        non_null = [str(r[col]).strip() for r in rows if r.get(col) and str(r[col]).strip()]
                        if not non_null:
                            merged_data[col] = None
                        elif len(set(non_null)) == 1:
                            merged_data[col] = non_null[0]
                        else:
                            # Frequency-wins: most common non-null value
                            merged_data[col] = Counter(non_null).most_common(1)[0][0]

                canonical_row = rows[0]
                duplicate_rows = rows[1:]

                # Step 4a: Update canonical row with merged data
                self.data_layer.update_record(table_name, canonical_row["row_id"], merged_data)

                # Step 4b: Merge provenance — collect all chunk IDs from all duplicate rows
                all_chunk_ids: List[str] = []
                for row in rows:
                    try:
                        provenance_list = self.data_layer.get_provenance(
                            row_ids=[row["row_id"]]
                        )
                        for p in provenance_list:
                            raw = p.chunk_ids
                            ids = raw if isinstance(raw, list) else json.loads(raw)
                            all_chunk_ids.extend(ids)
                    except Exception as e:
                        logger.warning(f"[Consolidation] Could not read provenance for {row['row_id']}: {e}")

                # Deduplicate chunk IDs
                all_chunk_ids = list(dict.fromkeys(all_chunk_ids))

                self.data_layer.update_provenance_chunks(canonical_row["row_id"], all_chunk_ids)

                # Step 4c: Delete duplicate rows and their provenance
                for dup_row in duplicate_rows:
                    self.data_layer.delete_provenance(dup_row["row_id"])
                    self.data_layer.delete_record(table_name, dup_row["row_id"])
                    deleted_count += 1

                merged_count += 1

            logger.info(
                f"[Consolidation] '{table_name}': merged {merged_count} groups, "
                f"deleted {deleted_count} duplicate rows."
            )

    def _proactive_entity_resolution(self, lattice) -> None:
        """
        Perform proactive entity resolution on join keys.
        Aligns join columns so Phase 2 can execute joins instantly.

        Uses the actual ON-clause column pairs stored in
        ``lattice.join_column_pairs`` (populated from the workload SQL)
        instead of guessing column names by substring heuristics.
        """
        column_pairs = getattr(lattice, "join_column_pairs", [])
        if not column_pairs and not lattice.join_pairs:
            logger.info("No joins in workload, skipping entity resolution")
            return

        if not column_pairs:
            logger.warning(
                "Lattice has join_pairs but no join_column_pairs "
                "(ON-clause columns missing). Skipping entity resolution."
            )
            return

        seen: set = set()
        unique_pairs = []
        for lt, lc, rt, rc in column_pairs:
            key = (lt, lc, rt, rc)
            rev = (rt, rc, lt, lc)
            if key not in seen and rev not in seen:
                seen.add(key)
                unique_pairs.append((lt, lc, rt, rc))

        logger.info(
            f"Performing entity resolution on {len(unique_pairs)} join column pair(s)"
        )

        from entity_resolver import EntityMention

        for left_table, left_col, right_table, right_col in unique_pairs:
            logger.info(
                f"Resolving join: {left_table}.{left_col} ↔ {right_table}.{right_col}"
            )

            left_values = self.data_layer.get_distinct_values(left_table, left_col)
            right_values = self.data_layer.get_distinct_values(right_table, right_col)

            logger.info(
                f"  {left_table}.{left_col}: {len(left_values)} values, "
                f"  {right_table}.{right_col}: {len(right_values)} values"
            )

            mentions = []
            for value in left_values:
                if value and str(value).strip():
                    mentions.append(EntityMention(
                        mention_id=f"{left_table}_{left_col}_{value}",
                        value=str(value),
                        table_name=left_table,
                        column_name=left_col,
                        semantic_type="JOIN_KEY",
                    ))
            for value in right_values:
                if value and str(value).strip():
                    mentions.append(EntityMention(
                        mention_id=f"{right_table}_{right_col}_{value}",
                        value=str(value),
                        table_name=right_table,
                        column_name=right_col,
                        semantic_type="JOIN_KEY",
                    ))

            if len(mentions) < 2:
                logger.warning(
                    f"Not enough values to resolve for "
                    f"{left_table}.{left_col} ↔ {right_table}.{right_col}"
                )
                continue

            logger.info(f"Running entity resolution on {len(mentions)} mentions")
            result = self.entity_resolver.resolve_entities(mentions)
            logger.info(f"Resolved into {result.total_clusters} clusters")

            if not result.canonical_map:
                logger.info(
                    f"No mismatches found for "
                    f"{left_table}.{left_col} ↔ {right_table}.{right_col}"
                )
                continue

            self.data_layer.update_column_values(
                left_table, left_col, result.canonical_map
            )
            self.data_layer.update_column_values(
                right_table, right_col, result.canonical_map
            )

            logger.info(
                f"Aligned {len(result.canonical_map)} value(s) for "
                f"{left_table}.{left_col} ↔ {right_table}.{right_col}"
            )

        logger.info("Entity resolution complete - joins are now aligned")
    
    def _save_preprocessing_results(self, lattice) -> None:
        """Save preprocessing results to cache."""
        results_file = self.cache_dir / "preprocessing_results.json"
        
        extraction_plan = self.lattice_planner.get_extraction_plan()
        
        with open(results_file, 'w') as f:
            json.dump(extraction_plan, f, indent=2)
        
        logger.info(f"Saved preprocessing results to {results_file}")
        
        # Save attribute index
        attr_index_file = self.cache_dir / "attribute_index.json"
        self.extractor.attribute_index.save(attr_index_file)
        logger.info(f"Saved attribute index to {attr_index_file}")
    
    # ========================================================================
    # Phase 2: Runtime Execution
    # ========================================================================

    def restore_lattice(self, workload_queries: List[str]) -> None:
        """
        Re-parse the training workload to rebuild the in-memory lattice without
        re-running any extraction.  Call this in Phase 2 after loading a
        preprocessed DB so the delta engine knows the table schemas and predicate
        literals.

        Semantic type identification (LLM call) is skipped — the DB tables
        already exist with the correct column types from Phase 1.
        """
        logger.info(f"Restoring lattice from {len(workload_queries)} training queries")
        self.lattice_planner.parse_workload(workload_queries, identify_types=False)
        logger.info(
            f"Lattice restored: {len(self.lattice_planner.lattice.tables)} tables"
        )
        
        # Load attribute index for smart column delta.
        # The index is a required output of preprocessing — if it is missing the
        # run directory is incomplete and continuing would silently fall back to
        # exhaustive extraction (potentially 9 000+ chunks per query).
        from attribute_index import AttributeIndex
        attr_index_file = self.cache_dir / "attribute_index.json"
        if not attr_index_file.exists():
            raise RuntimeError(
                f"Attribute index not found at {attr_index_file}. "
                f"Re-run preprocessing to rebuild it before executing queries."
            )
        self.extractor.attribute_index = AttributeIndex.load(attr_index_file)
        logger.info(f"Loaded attribute index from {attr_index_file}")

    # ========================================================================

    def execute_query(self, query: str) -> QueryResult:
        """
        Execute query with delta engine.
        
        Args:
            query: SQL query string
            
        Returns:
            QueryResult
        """
        logger.info("=" * 80)
        logger.info("PHASE 2: RUNTIME QUERY EXECUTION")
        logger.info("=" * 80)
        logger.info(f"Query: {query}")
        
        start_time = time.time()
        
        try:
            # Analyze query
            plan = self.delta_engine.analyze_query(query)
            
            logger.info(f"Delta plan: {plan.delta_type.value}")
            logger.info(f"Missing columns: {plan.missing_columns}")
            logger.info(f"Missing predicates: {plan.missing_predicates}")
            
            # Execute delta (extracts / enriches / aligns as needed)
            delta_result = self.delta_engine.execute_delta(plan, query)

            if not delta_result.success:
                raise Exception(f"Delta execution failed: {delta_result.error}")

            # Execute the SQL query against the synthesized DB
            results = self.data_layer.execute_sql(query)
            logger.info(f"SQL executed: {len(results)} rows returned")
            
            execution_time = time.time() - start_time
            
            result = QueryResult(
                success=True,
                results=results,
                delta_type=plan.delta_type.value,
                rows_extracted=delta_result.rows_extracted,
                rows_enriched=delta_result.rows_enriched,
                execution_time=execution_time
            )
            
            logger.info("=" * 80)
            logger.info("QUERY EXECUTION COMPLETE")
            logger.info(f"Time: {execution_time:.2f}s")
            logger.info(f"Delta type: {plan.delta_type.value}")
            logger.info(f"Rows extracted: {delta_result.rows_extracted}")
            logger.info(f"Rows enriched: {delta_result.rows_enriched}")
            logger.info("=" * 80)
            
            return result
        
        except Exception as e:
            logger.error(f"Query execution failed: {e}", exc_info=True)
            execution_time = time.time() - start_time
            
            return QueryResult(
                success=False,
                results=[],
                delta_type="error",
                rows_extracted=0,
                rows_enriched=0,
                execution_time=execution_time,
                error=str(e)
            )
    
    # ========================================================================
    # Utility Methods
    # ========================================================================
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get system statistics."""
        stats = {
            "dataset": self.dataset,
            "total_chunks": self.data_layer.count_chunks(),
            "tables": [],
            "metadata_entries": len(self.data_layer.get_metadata())
        }
        
        # Get table statistics
        metadata_entries = self.data_layer.get_metadata()
        tables_set = set(entry.table_name for entry in metadata_entries)
        
        for table_name in tables_set:
            table_metadata = self.data_layer.get_metadata(table_name=table_name)
            
            stats["tables"].append({
                "name": table_name,
                "columns": len(table_metadata),
                "status": "materialized" if table_metadata else "pending"
            })
        
        return stats
    
    def clear_cache(self) -> None:
        """Clear all caches."""
        import shutil
        
        if self.cache_dir.exists():
            shutil.rmtree(self.cache_dir)
            self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Cache cleared")
    
    def close(self) -> None:
        """Close all connections."""
        self.data_layer.close()
        logger.info("WDIRS runner closed")


# ============================================================================
# CLI Interface
# ============================================================================

def main():
    """Main CLI entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="WDIRS - Workload-Driven Incremental Relational Synthesis")
    parser.add_argument("dataset", help="Dataset name")
    parser.add_argument("--preprocess", action="store_true", help="Run preprocessing")
    parser.add_argument("--query", help="Execute SQL query")
    parser.add_argument("--workload", help="Path to workload directory")
    parser.add_argument("--stats", action="store_true", help="Show statistics")
    parser.add_argument("--clear-cache", action="store_true", help="Clear cache")
    
    args = parser.parse_args()
    
    # Initialize runner
    runner = WDIRSRunner(args.dataset)
    
    try:
        if args.clear_cache:
            runner.clear_cache()
            print("Cache cleared")
        
        if args.preprocess:
            result = runner.preprocess(args.workload)
            
            if result.success:
                print(f"\nPreprocessing complete!")
                print(f"Tables: {len(result.tables_processed)}")
                print(f"Chunks: {result.total_chunks}")
                print(f"Records: {result.total_records}")
                print(f"Time: {result.preprocessing_time:.2f}s")
            else:
                print(f"\nPreprocessing failed: {result.error}")
                sys.exit(1)
        
        if args.query:
            result = runner.execute_query(args.query)
            
            if result.success:
                print(f"\nQuery executed successfully!")
                print(f"Delta type: {result.delta_type}")
                print(f"Rows extracted: {result.rows_extracted}")
                print(f"Rows enriched: {result.rows_enriched}")
                print(f"Time: {result.execution_time:.2f}s")
                print(f"\nResults: {len(result.results)} rows")
            else:
                print(f"\nQuery failed: {result.error}")
                sys.exit(1)
        
        if args.stats:
            stats = runner.get_statistics()
            print(f"\nSystem Statistics:")
            print(f"Dataset: {stats['dataset']}")
            print(f"Total chunks: {stats['total_chunks']}")
            print(f"Metadata entries: {stats['metadata_entries']}")
            print(f"\nTables:")
            for table in stats['tables']:
                print(f"  - {table['name']}: {table['columns']} columns ({table['status']})")
    
    finally:
        runner.close()


if __name__ == "__main__":
    main()
