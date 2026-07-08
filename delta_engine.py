"""
Delta Engine for QuWARTS.
Implements runtime incremental query execution with row and column deltas.
"""

import json
import logging
import time
import re
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass
from enum import Enum
import uuid

import sqlglot
from sqlglot import parse_one, exp
from sqlalchemy import text

from data_layer import DataLayer, TextChunk
from lattice_planner import LatticePlanner
from extractor import ConstrainedExtractor
from entity_resolver import EntityResolver, EntityMention, extract_mentions_from_records, apply_canonical_map
from config import STATUS_PARTIAL, STATUS_FULL

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

class DeltaType(Enum):
    """Type of delta required."""
    CACHE_HIT = "cache_hit"  # Query can be answered from existing data
    ROW_DELTA = "row_delta"  # Need to extract new rows
    COLUMN_DELTA = "column_delta"  # Need to enrich existing rows
    MIXED_DELTA = "mixed_delta"  # Need both new rows and new columns
    JOIN_ALIGNMENT = "join_alignment"  # Need to align join keys

@dataclass
class DeltaPlan:
    """Plan for executing a query with deltas."""
    delta_type: DeltaType
    missing_columns: List[str]
    missing_predicates: List[str]
    missing_predicates_by_table: Dict[str, List[str]]  # table → predicates that apply to it
    tables_involved: List[str]
    requires_extraction: bool
    requires_enrichment: bool
    requires_join_alignment: bool
    estimated_cost: float

@dataclass
class DeltaExecutionResult:
    """Result of delta execution."""
    success: bool
    rows_extracted: int
    rows_enriched: int
    execution_time: float
    error: Optional[str] = None


# ============================================================================
# Delta Engine
# ============================================================================

class DeltaEngine:
    """
    Implements runtime incremental query execution.
    Calculates and executes deltas to answer queries efficiently.
    """
    
    def __init__(
        self,
        data_layer: DataLayer,
        lattice_planner: LatticePlanner,
        extractor: ConstrainedExtractor,
        entity_resolver: EntityResolver
    ):
        """Initialize delta engine."""
        self.data_layer = data_layer
        self.lattice_planner = lattice_planner
        self.extractor = extractor
        self.entity_resolver = entity_resolver
        # Populated by QuWARTSRunner; used to avoid row-delta duplicate explosions
        # by upserting on known identity columns instead of blind inserts.
        self.identity_columns: Dict[str, Optional[str]] = {}
        
        logger.info("DeltaEngine initialized")
    
    # ========================================================================
    # Query Analysis
    # ========================================================================
    
    def analyze_query(self, query: str) -> DeltaPlan:
        """
        Analyze query and determine delta plan.
        
        Args:
            query: SQL query string
            
        Returns:
            DeltaPlan with execution strategy
        """
        logger.info("Analyzing query for delta calculation")
        
        # Parse query
        try:
            parsed = parse_one(query, dialect="postgres")
        except Exception as e:
            logger.error(f"Failed to parse query: {e}")
            raise
        
        # Extract query components
        tables = self._extract_tables(parsed)
        columns = self._extract_columns(parsed)
        predicates = self._extract_predicates(parsed)
        joins = self._extract_joins(parsed)
        
        logger.debug(f"Query components: tables={tables}, columns={len(columns)}, "
                    f"predicates={len(predicates)}, joins={len(joins)}")
        
        # Check materialization for each table
        missing_columns_all = []
        missing_predicates_all = []
        missing_predicates_by_table: Dict[str, List[str]] = {}
        
        for table_name in tables:
            # Get required columns for this table
            table_columns = [col for tbl, col in columns if tbl == table_name]
            table_predicates = [pred for tbl, pred in predicates if tbl == table_name]
            
            # Check metadata registry
            is_complete, missing_cols, missing_preds = self.data_layer.check_materialization(
                table_name,
                table_columns,
                table_predicates
            )
            
            missing_columns_all.extend(missing_cols)
            missing_predicates_all.extend(missing_preds)
            if missing_preds:
                missing_predicates_by_table[table_name] = missing_preds
        
        # Determine delta type
        delta_type = self._determine_delta_type(
            missing_columns_all,
            missing_predicates_all,
            joins
        )
        
        # Build delta plan
        plan = DeltaPlan(
            delta_type=delta_type,
            missing_columns=missing_columns_all,
            missing_predicates=missing_predicates_all,
            missing_predicates_by_table=missing_predicates_by_table,
            tables_involved=list(tables),
            requires_extraction=delta_type in [DeltaType.ROW_DELTA, DeltaType.MIXED_DELTA],
            requires_enrichment=delta_type in [DeltaType.COLUMN_DELTA, DeltaType.MIXED_DELTA],
            requires_join_alignment=delta_type == DeltaType.JOIN_ALIGNMENT or len(joins) > 0,
            estimated_cost=self._estimate_cost(delta_type, missing_columns_all, missing_predicates_all)
        )
        
        logger.info(f"Delta plan: {plan.delta_type.value}, "
                   f"missing_cols={len(missing_columns_all)}, "
                   f"missing_preds={len(missing_predicates_all)}")
        
        return plan
    
    def _extract_tables(self, parsed: exp.Expression) -> Set[str]:
        """Extract table names from parsed query."""
        tables = set()
        for table in parsed.find_all(exp.Table):
            if table.name:
                tables.add(table.name.lower())
        return tables
    
    def _primary_table(self, parsed: exp.Expression) -> Optional[str]:
        """Return the first table name found in the FROM clause (for unqualified columns)."""
        for table in parsed.find_all(exp.Table):
            if table.name:
                return table.name.lower()
        return None

    def _extract_columns(self, parsed: exp.Expression) -> List[Tuple[str, str]]:
        """Extract (table, column) pairs, inferring table from FROM for unqualified columns."""
        columns = []
        primary_table = self._primary_table(parsed)

        for select in parsed.find_all(exp.Select):
            for projection in select.expressions:
                if isinstance(projection, exp.Column):
                    table = (projection.table or primary_table)
                    column = projection.name
                    if table and column:
                        columns.append((table.lower(), column.lower()))

        for where in parsed.find_all(exp.Where):
            for column in where.find_all(exp.Column):
                table = (column.table or primary_table)
                col_name = column.name
                if table and col_name:
                    columns.append((table.lower(), col_name.lower()))

        return columns

    def _extract_predicates(self, parsed: exp.Expression) -> List[Tuple[str, str]]:
        """Extract (table, predicate) pairs, inferring table from FROM for unqualified columns."""
        predicates = []
        primary_table = self._primary_table(parsed)

        for where in parsed.find_all(exp.Where):
            for comparison in where.find_all(exp.EQ, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.NEQ):
                left = comparison.left
                right = comparison.right

                if isinstance(left, exp.Column):
                    table = (left.table or primary_table)
                    column = left.name

                    if table and column:
                        operator = self._get_operator(comparison)
                        value = self._get_value(right)
                        predicate = f"{column} {operator} {value}"
                        predicates.append((table.lower(), predicate))
        
        return predicates
    
    def _extract_joins(self, parsed: exp.Expression) -> List[Tuple[str, str, str, str]]:
        """
        Extract join information as:
            (left_table, left_column, right_table, right_column)

        We only extract explicit column-to-column equality joins
        (e.g. a.x = b.y), because join alignment requires both side-specific
        column names and table names.
        """
        joins: List[Tuple[str, str, str, str]] = []
        seen: Set[Tuple[str, str, str, str]] = set()

        for join in parsed.find_all(exp.Join):
            on_expr = join.args.get("on")
            if on_expr is None:
                continue

            for eq in on_expr.find_all(exp.EQ):
                left = eq.left
                right = eq.right
                if not isinstance(left, exp.Column) or not isinstance(right, exp.Column):
                    continue
                if not left.table or not right.table:
                    continue

                key = (
                    left.table.lower(),
                    left.name.lower(),
                    right.table.lower(),
                    right.name.lower(),
                )
                if key not in seen:
                    seen.add(key)
                    joins.append(key)

        return joins
    
    def _get_operator(self, comparison: exp.Expression) -> str:
        """Get operator string."""
        if isinstance(comparison, exp.EQ):
            return "="
        elif isinstance(comparison, exp.GT):
            return ">"
        elif isinstance(comparison, exp.LT):
            return "<"
        elif isinstance(comparison, exp.GTE):
            return ">="
        elif isinstance(comparison, exp.LTE):
            return "<="
        elif isinstance(comparison, exp.NEQ):
            return "!="
        return "="
    
    def _get_value(self, expr: exp.Expression) -> str:
        """Extract value from expression."""
        if isinstance(expr, exp.Literal):
            return expr.this
        elif isinstance(expr, exp.Column):
            return expr.name
        return str(expr)
    
    def _determine_delta_type(
        self,
        missing_columns: List[str],
        missing_predicates: List[str],
        joins: List[Tuple[str, str, str, str]]
    ) -> DeltaType:
        """Determine type of delta required."""
        has_missing_columns = len(missing_columns) > 0
        has_missing_predicates = len(missing_predicates) > 0
        has_joins = len(joins) > 0
        
        if not has_missing_columns and not has_missing_predicates:
            if has_joins:
                return DeltaType.JOIN_ALIGNMENT
            return DeltaType.CACHE_HIT
        
        if has_missing_columns and has_missing_predicates:
            return DeltaType.MIXED_DELTA
        
        if has_missing_columns:
            return DeltaType.COLUMN_DELTA
        
        if has_missing_predicates:
            return DeltaType.ROW_DELTA
        
        return DeltaType.CACHE_HIT
    
    def _estimate_cost(
        self,
        delta_type: DeltaType,
        missing_columns: List[str],
        missing_predicates: List[str]
    ) -> float:
        """Estimate execution cost."""
        if delta_type == DeltaType.CACHE_HIT:
            return 0.1
        
        if delta_type == DeltaType.ROW_DELTA:
            return len(missing_predicates) * 2.0
        
        if delta_type == DeltaType.COLUMN_DELTA:
            return len(missing_columns) * 1.5
        
        if delta_type == DeltaType.MIXED_DELTA:
            return len(missing_columns) * 1.5 + len(missing_predicates) * 2.0
        
        if delta_type == DeltaType.JOIN_ALIGNMENT:
            return 3.0
        
        return 1.0
    
    # ========================================================================
    # Delta Execution
    # ========================================================================
    
    def execute_delta(
        self,
        plan: DeltaPlan,
        query: str
    ) -> DeltaExecutionResult:
        """
        Execute delta plan to materialize missing data.
        
        Args:
            plan: Delta plan
            query: Original SQL query
            
        Returns:
            DeltaExecutionResult
        """
        logger.info(f"Executing delta: {plan.delta_type.value}")
        start_time = time.time()
        
        rows_extracted = 0
        rows_enriched = 0
        
        try:
            if plan.delta_type == DeltaType.CACHE_HIT:
                logger.info("Cache hit - no delta execution needed")
            
            elif plan.delta_type == DeltaType.ROW_DELTA:
                rows_extracted = self._execute_row_delta(
                    plan.tables_involved,
                    plan.missing_predicates,
                    plan.missing_predicates_by_table
                )

            elif plan.delta_type == DeltaType.COLUMN_DELTA:
                rows_enriched = self._execute_column_delta(
                    plan.tables_involved,
                    plan.missing_columns
                )

            elif plan.delta_type == DeltaType.MIXED_DELTA:
                rows_extracted = self._execute_row_delta(
                    plan.tables_involved,
                    plan.missing_predicates,
                    plan.missing_predicates_by_table
                )
                rows_enriched = self._execute_column_delta(
                    plan.tables_involved,
                    plan.missing_columns
                )
            
            elif plan.delta_type == DeltaType.JOIN_ALIGNMENT:
                self._execute_join_alignment(query)

            if plan.requires_join_alignment and plan.delta_type != DeltaType.JOIN_ALIGNMENT:
                logger.info("Running join alignment after extraction/enrichment")
                self._execute_join_alignment(query)
            
            execution_time = time.time() - start_time
            
            return DeltaExecutionResult(
                success=True,
                rows_extracted=rows_extracted,
                rows_enriched=rows_enriched,
                execution_time=execution_time
            )
        
        except Exception as e:
            logger.error(f"Delta execution failed: {e}")
            execution_time = time.time() - start_time
            
            return DeltaExecutionResult(
                success=False,
                rows_extracted=rows_extracted,
                rows_enriched=rows_enriched,
                execution_time=execution_time,
                error=str(e)
            )
    
    def _build_runtime_normalization_hints(
        self,
        missing_predicates: List[str]
    ) -> Dict[str, List[str]]:
        """
        Build normalization hints from runtime query predicate literals.

        For a runtime predicate like 'country = UK', the extractor must be told
        to store 'UK' — not 'United Kingdom' or any other form.  These hints are
        derived solely from the runtime query, NOT from the workload, so they
        reflect exactly what the query expects to find in the DB.
        """
        hints: Dict[str, List[str]] = {}
        for pred in missing_predicates:
            # Only equality predicates define an expected stored value.
            # Predicates like "age > 25" don't constrain string form.
            if "=" not in pred or "!=" in pred or ">=" in pred or "<=" in pred:
                continue
            col, _, val = pred.partition("=")
            col = col.strip()
            val = val.strip().strip("'\"")
            if col and val:
                hints.setdefault(col, [])
                if val not in hints[col]:
                    hints[col].append(val)
        return hints

    def _execute_row_delta(
        self,
        tables: List[str],
        missing_predicates: List[str],
        missing_predicates_by_table: Optional[Dict[str, List[str]]] = None
    ) -> int:
        """
        Execute row delta: extract new rows matching missing predicates.
        
        Uses missing_predicates_by_table (table → predicates) to only extract
        from tables that actually have the missing predicate. Falls back to
        all tables if the per-table mapping is not available.
        """
        logger.info(f"Executing row delta for {len(tables)} tables")

        runtime_hints = self._build_runtime_normalization_hints(missing_predicates)
        if runtime_hints:
            logger.info(f"Runtime normalization hints: {runtime_hints}")

        total_rows = 0

        for table_name in tables:
            # Determine which predicates apply to this table
            if missing_predicates_by_table is not None:
                table_preds = missing_predicates_by_table.get(table_name, [])
                if not table_preds:
                    logger.info(
                        f"[Smart Row Delta] Skipping '{table_name}': "
                        f"no missing predicates apply to this table"
                    )
                    continue
            else:
                table_preds = missing_predicates
            candidate_chunk_ids = self.data_layer.get_candidates(table_name)
            if not candidate_chunk_ids:
                logger.warning(f"No candidate chunks for {table_name}")
                continue

            # Only load chunks after the attribute index narrows the candidate set,
            # to avoid materialising the full 9000+ candidate list in memory when
            # the index or keyword filter can safely reduce scope first.
            schema = self.lattice_planner.get_table_schema(table_name)

            # SMART ROW DELTA: Use attribute index to target chunks mentioning predicate columns.
            # Extract ONLY the column name (first token before the operator) from each predicate.
            # The old approach used re.findall on the whole predicate string, which also captured
            # value tokens like "New" and "York" from "city = New York" and fed them as column
            # lookups into the attribute index — producing false hits and an inflated union.
            import re
            predicate_columns = set()
            for pred in table_preds:
                # Predicate format: "<column> <operator> <value>" (from _extract_predicates).
                # Only the first whitespace-delimited token is the column name.
                col = pred.split()[0].strip() if pred.split() else ""
                if col and re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col):
                    predicate_columns.add(col)

            if predicate_columns:
                # Query attribute index for chunks that mention these columns
                targeted_chunk_ids = set()
                for col in predicate_columns:
                    col_chunks = self.extractor.attribute_index.find_chunks_for_column(
                        table_name, col, top_k=500
                    )
                    targeted_chunk_ids.update(col_chunks)

                if targeted_chunk_ids:
                    candidate_set = set(candidate_chunk_ids)
                    filtered_chunk_ids = list(targeted_chunk_ids & candidate_set)
                    if filtered_chunk_ids:
                        chunks = self.data_layer.get_chunks_by_ids(filtered_chunk_ids)
                        logger.info(
                            f"[Smart Row Delta] {table_name}: narrowed from "
                            f"{len(candidate_chunk_ids)} to {len(chunks)} chunks "
                            f"using attribute index for {predicate_columns}"
                        )
                    else:
                        # The index returned chunk IDs, but none of them exist in the
                        # current candidate set.  This means the index was built from a
                        # different preprocessing run than the working DB — a stale index
                        # cannot be trusted.  Failing loudly is better than silently
                        # extracting thousands of unrelated chunks.
                        raise RuntimeError(
                            f"[Smart Row Delta] Attribute index for '{table_name}' is stale: "
                            f"it returned {len(targeted_chunk_ids)} chunk ID(s) for columns "
                            f"{predicate_columns} but none exist in the current candidate set "
                            f"({len(candidate_chunk_ids)} candidates). "
                            f"Re-run preprocessing to rebuild the index against the current DB."
                        )
                else:
                    # The index is loaded but has no entry for these predicate columns —
                    # the column was not seen during preprocessing (novel predicate) or
                    # every matched attribute was over-broad.  We cannot narrow the
                    # candidate set, so fall back to all candidates.  The keyword filter
                    # below will still limit extraction to chunks that actually contain
                    # the predicate value (for equality predicates).
                    chunks = self.data_layer.get_chunks_by_ids(candidate_chunk_ids)
                    logger.warning(
                        f"[Smart Row Delta] {table_name}: attribute index has no usable "
                        f"entries for {predicate_columns} — scanning all "
                        f"{len(chunks)} candidates (column not seen during preprocessing)."
                    )
            else:
                # No column name could be parsed from any predicate (e.g. purely numeric
                # or malformed predicates).  Scan all candidates.
                chunks = self.data_layer.get_chunks_by_ids(candidate_chunk_ids)
                logger.warning(
                    f"[Smart Row Delta] {table_name}: could not extract column names from "
                    f"predicates {table_preds} — scanning all {len(chunks)} candidates."
                )

            # Keyword-filter chunks to those likely relevant to missing predicates
            filtered_chunks = self._filter_chunks_by_predicates(chunks, table_preds)
            if not filtered_chunks:
                logger.info(f"No chunks match missing predicates for {table_name}")
                continue

            stabilized = self.extractor.get_stabilized_schema(table_name)
            constrained_keys = stabilized.frozen_keys if stabilized else None

            chunk_texts = [c.content for c in filtered_chunks]
            chunk_ids_list = [c.chunk_id for c in filtered_chunks]
            chunk_doc_map = {c.chunk_id: c.doc_id for c in filtered_chunks}
            chunk_text_map = {c.chunk_id: c.content for c in filtered_chunks}

            results = self.extractor.extract_batch_with_predicates(
                chunk_texts,
                chunk_ids_list,
                table_name,
                schema,
                constrained_keys,
                table_preds,
                runtime_hints
            )

            # Ensure the dynamic table exists before inserting
            from quwarts_runner import semantic_to_sql_type
            sql_schema = {col: semantic_to_sql_type(sem_type)
                          for col, sem_type in schema.items()}
            self.data_layer.create_dynamic_table(table_name, sql_schema)

            # Prefer identity-key upsert when available to avoid inserting
            # duplicate rows for the same entity across many chunks.
            identity_col = (self.identity_columns or {}).get(table_name)
            if identity_col:
                triples: List[tuple] = []
                dropped_invalid = 0
                for result in results:
                    if result.error:
                        logger.warning(
                            f"Skipping chunk {result.chunk_id} in row delta: {result.error}"
                        )
                        continue
                    doc_id = chunk_doc_map.get(result.chunk_id, "")
                    chunk_text = chunk_text_map.get(result.chunk_id, "")
                    for record in result.records:
                        rec = dict(record)
                        ent = rec.get(identity_col)
                        ent_str = str(ent).strip() if ent is not None else ""
                        if not self._is_valid_identity_value(ent_str, chunk_text):
                            dropped_invalid += 1
                            continue
                        rec["_entity"] = ent_str
                        triples.append((rec, result.chunk_id, doc_id))

                table_rows = 0
                if triples:
                    row_pv, cell_pv = self.data_layer.upsert_by_entity(
                        table_name,
                        identity_col,
                        triples,
                        allow_insert_new_entities=False,
                    )
                    self.data_layer.bulk_insert_provenance(table_name, row_pv)
                    self.data_layer.bulk_insert_cell_provenance(cell_pv)
                    table_rows = len({rid for rid, _ in row_pv})
                if dropped_invalid:
                    logger.info(
                        f"[RowDelta] Dropped {dropped_invalid} records with invalid "
                        f"identity for {table_name}.{identity_col}"
                    )
            else:
                table_rows = 0
                for result in results:
                    if result.error:
                        logger.warning(
                            f"Skipping chunk {result.chunk_id} in row delta: {result.error}"
                        )
                        continue
                    for record in result.records:
                        row_id = self.data_layer.insert_record(table_name, record)
                        self.data_layer.insert_provenance(
                            row_id, table_name, [result.chunk_id]
                        )
                        table_rows += 1

            total_rows += table_rows
            logger.info(f"Row delta inserted {table_rows} rows into {table_name}")

            # Mark these predicates as materialized in the registry
            for predicate in table_preds:
                col = predicate.split()[0].strip()
                self.data_layer.update_metadata(
                    table_name,
                    col,
                    [predicate],
                    STATUS_PARTIAL,
                    table_rows
                )

        logger.info(f"Row delta complete: {total_rows} rows extracted")
        return total_rows

    @staticmethod
    def _normalize_text(s: str) -> str:
        s = (s or "").strip().lower()
        s = re.sub(r"[^\w\s]", " ", s)
        return " ".join(s.split())

    def _is_valid_identity_value(self, value: str, chunk_text: str) -> bool:
        """
        Generic identity validation for runtime row-delta:
        - non-empty / non-placeholder
        - not numeric-only
        - must be grounded in source chunk text (exact or normalized)
        """
        v = (value or "").strip()
        if not v:
            return False
        norm_v = self._normalize_text(v)
        if norm_v in {"name", "id", "label", "title", "unknown", "none", "null", "n a"}:
            return False
        if re.fullmatch(r"\d+", v):
            return False
        chunk = chunk_text or ""
        if v.lower() in chunk.lower():
            return True
        return norm_v in self._normalize_text(chunk)
    
    def _execute_column_delta(
        self,
        tables: List[str],
        missing_columns: List[str]
    ) -> int:
        """
        Execute column delta: enrich existing rows with missing column values.

        For each existing row we:
          1. Retrieve its source chunks via Row_Provenance.
          2. Ask the LLM to extract ONLY the missing columns from those chunks,
             providing the row's existing values as context so the LLM knows
             which entity to focus on.
          3. UPDATE the existing DB row with the newly extracted values.

        Returns:
            Number of rows enriched
        """
        logger.info(f"Executing column delta: missing columns={missing_columns}")

        import json as _json

        total_enriched = 0

        for table_name in tables:
            # Load all existing rows from the dynamic table
            try:
                existing_rows = self.data_layer.get_all_records(table_name)
            except Exception as e:
                raise RuntimeError(
                    f"Column delta failed: cannot read rows from '{table_name}': {e}"
                ) from e

            if not existing_rows:
                logger.warning(f"No existing rows in '{table_name}' to enrich")
                continue

            schema = self.lattice_planner.get_table_schema(table_name)
            system_cols = {"row_id", "created_at"}

            for row in existing_rows:
                row_id = row["row_id"]

                # Skip if row already has all missing columns populated
                already_filled = all(
                    row.get(col) not in (None, "", "null")
                    for col in missing_columns
                    if col in row
                )
                if already_filled and all(col in row for col in missing_columns):
                    continue

                # Retrieve source chunks for this row via provenance
                # OPTIMIZATION: Use entity → document mapping to only fetch chunks from the entity's document
                provenance_list = self.data_layer.get_provenance(row_ids=[row_id])
                if not provenance_list:
                    logger.warning(f"No provenance for row {row_id} in '{table_name}'")
                    continue

                chunk_ids_for_row = []
                for prov in provenance_list:
                    raw = prov.chunk_ids
                    ids = raw if isinstance(raw, list) else _json.loads(raw)
                    chunk_ids_for_row.extend(ids)
                
                # Get document ID(s) for this row from Cell_Provenance
                # Each entity belongs to exactly one document, so we should only extract from that document's chunks
                row_doc_ids = set()
                try:
                    cell_prov_query = f"""
                        SELECT DISTINCT doc_id 
                        FROM cell_provenance 
                        WHERE row_id = ?
                    """
                    with self.data_layer.engine.connect() as conn:
                        result = conn.execute(text(cell_prov_query), (row_id,))
                        row_doc_ids = {row[0] for row in result}
                except Exception as e:
                    logger.warning(f"Could not fetch doc_ids for row {row_id}: {e}")
                
                # Filter chunk_ids to only those from the row's documents
                if row_doc_ids:
                    all_chunks_for_row = self.data_layer.get_chunks_by_ids(list(dict.fromkeys(chunk_ids_for_row)))
                    document_scoped_chunks = [c for c in all_chunks_for_row if c.doc_id in row_doc_ids]
                    
                    if document_scoped_chunks:
                        logger.debug(
                            f"[Document-Scoped] Row {row_id}: narrowed from "
                            f"{len(all_chunks_for_row)} chunks to {len(document_scoped_chunks)} "
                            f"(document scope: {row_doc_ids})"
                        )
                        chunk_ids_for_row = [c.chunk_id for c in document_scoped_chunks]
                    else:
                        logger.warning(
                            f"[Document-Scoped] No chunks found in document scope {row_doc_ids} "
                            f"for row {row_id}, falling back to all provenance chunks"
                        )
                
                # SMART COLUMN DELTA: Use attribute index to target relevant chunks within the document
                # First, try to find chunks that likely contain the missing columns
                targeted_chunk_ids = set()
                for col in missing_columns:
                    col_chunks = self.extractor.attribute_index.find_chunks_for_column(
                        table_name, col, top_k=50
                    )
                    targeted_chunk_ids.update(col_chunks)
                
                # Intersect with row's document-scoped chunks (only extract from entity's document)
                if targeted_chunk_ids:
                    provenance_chunk_set = set(chunk_ids_for_row)
                    filtered_chunk_ids = list(targeted_chunk_ids & provenance_chunk_set)
                    
                    if filtered_chunk_ids:
                        logger.info(
                            f"[Smart Column Delta] Row {row_id}: narrowed from "
                            f"{len(chunk_ids_for_row)} document chunks to {len(filtered_chunk_ids)} "
                            f"using attribute index for {missing_columns}"
                        )
                        chunk_ids_for_row = filtered_chunk_ids
                    else:
                        logger.info(
                            f"[Smart Column Delta] No overlap between attribute index "
                            f"and document-scoped chunks for row {row_id}, using all document chunks"
                        )

                chunks = self.data_layer.get_chunks_by_ids(list(dict.fromkeys(chunk_ids_for_row)))
                if not chunks:
                    logger.warning(f"Source chunks missing for row {row_id}")
                    continue

                # Build context string from existing non-null values
                existing_context = {
                    k: v for k, v in row.items()
                    if k not in system_cols and v not in (None, "", "null")
                    and k not in missing_columns
                }
                context_str = ", ".join(
                    f'{k}="{v}"' for k, v in existing_context.items()
                )

                # For each source chunk, run a targeted extraction prompt
                # asking only for the missing columns for this specific entity.
                merged_values: Dict[str, Any] = {}
                for chunk in chunks:
                    missing_keys_str = ", ".join(f'"{c}"' for c in missing_columns)
                    prompt = (
                        f"You are extracting data for table '{table_name}'.\n"
                        f"We already have this record: {context_str}\n"
                        f"From the text below, extract ONLY these missing fields: [{missing_keys_str}] "
                        f"for the entity described above.\n"
                        f"Return a JSON object with only those keys. "
                        f"If a value is not present, use null.\n\n"
                        f"Text:\n{chunk.content}\n\n"
                        f"Output (JSON only):"
                    )

                    try:
                        response = self.extractor.llm_client.generate(
                            prompt,
                            max_tokens=512,
                            temperature=0.0
                        )
                        json_str = self.extractor._extract_json(response)
                        if json_str:
                            extracted = _json.loads(json_str)
                            if isinstance(extracted, dict):
                                for col in missing_columns:
                                    if col in extracted and extracted[col] not in (None, "", "null"):
                                        # First non-null value wins across chunks
                                        if col not in merged_values:
                                            merged_values[col] = extracted[col]
                    except Exception as e:
                        logger.warning(f"Column delta LLM call failed for row {row_id}: {e}")
                        continue

                if not merged_values:
                    logger.warning(f"No values extracted for row {row_id} missing cols {missing_columns}")
                    continue

                # Update only the columns we actually extracted
                self.data_layer.update_record(table_name, row_id, merged_values)
                total_enriched += 1

            logger.info(f"Column delta enriched {total_enriched} rows in '{table_name}'")

            # Mark columns as materialized in the registry
            for column in missing_columns:
                self.data_layer.update_metadata(
                    table_name,
                    column,
                    [],
                    STATUS_FULL,
                    total_enriched
                )

        logger.info(f"Column delta complete: {total_enriched} rows enriched")
        return total_enriched
    
    def _execute_join_alignment(self, query: str) -> None:
        """
        JIT join alignment: resolve entity references across join-key columns
        so that SQL joins produce correct matches.
        """
        logger.info("Executing JIT join alignment")

        parsed = parse_one(query, dialect="postgres")
        joins = self._extract_joins(parsed)

        for left_table, left_column, right_table, right_column in joins:
            logger.info(
                f"Aligning join: {left_table}.{left_column} ↔ {right_table}.{right_column}"
            )

            # Query actual distinct values from both tables
            left_values = self.data_layer.get_distinct_values(left_table, left_column)
            right_values = self.data_layer.get_distinct_values(right_table, right_column)

            if not left_values or not right_values:
                logger.warning(
                    f"Skipping join alignment for {left_table}↔{right_table}: "
                    f"one side has no values"
                )
                continue

            logger.info(
                f"  {left_table}.{left_column}: {len(left_values)} values, "
                f"  {right_table}.{right_column}: {len(right_values)} values"
            )

            # Pass 1 (deterministic): normalized exact matching across both sides.
            # This is robust for common formatting drift (case, punctuation, spacing).
            left_norm: Dict[str, List[str]] = {}
            right_norm: Dict[str, List[str]] = {}
            for v in left_values:
                n = self._normalize_text(v)
                if n:
                    left_norm.setdefault(n, []).append(v)
            for v in right_values:
                n = self._normalize_text(v)
                if n:
                    right_norm.setdefault(n, []).append(v)

            overlap_norms = set(left_norm.keys()) & set(right_norm.keys())
            canonical_map: Dict[str, str] = {}
            for n in overlap_norms:
                # Prefer a stable canonical form from the right side (join target),
                # choosing the shortest non-empty variant.
                right_variants = sorted(
                    [x for x in right_norm[n] if x and x.strip()],
                    key=lambda s: (len(s.strip()), s.lower()),
                )
                canonical = right_variants[0] if right_variants else right_norm[n][0]
                for raw in left_norm[n]:
                    canonical_map[raw] = canonical
                for raw in right_norm[n]:
                    canonical_map[raw] = canonical

            logger.info(
                "  Normalized exact overlap: %d key group(s), %d mapped values",
                len(overlap_norms),
                len(canonical_map),
            )

            # Pass 2 (semantic): only for values not matched by normalized overlap.
            unresolved_left = [v for v in left_values if v not in canonical_map]
            unresolved_right = [v for v in right_values if v not in canonical_map]
            if unresolved_left and unresolved_right:
                semantic_map = self.entity_resolver.align_join_keys(
                    unresolved_left,
                    unresolved_right,
                    left_table,
                    right_table,
                    f"{left_column}↔{right_column}"
                )
                canonical_map.update(semantic_map)

            if not canonical_map:
                logger.info(f"No join key mismatches found for {left_table}↔{right_table}")
                continue

            # Apply canonical forms to both tables
            self.data_layer.update_column_values(left_table, left_column, canonical_map)
            self.data_layer.update_column_values(right_table, right_column, canonical_map)

            logger.info(
                f"Aligned {len(canonical_map)} join key(s) between "
                f"{left_table} and {right_table}"
            )
    
    def _filter_chunks_by_predicates(
        self,
        chunks: List[TextChunk],
        predicates: List[str]
    ) -> List[TextChunk]:
        """
        Filter chunks that are likely to contain data satisfying the given predicates.

        For equality predicates (col = 'value') we search for the *value* literal in
        the chunk text.  Searching for the column name is useless because column names
        are schema artefacts that almost never appear verbatim in the source documents,
        and including them makes the filter a no-op (everything passes).

        For range predicates (col > X) there is no specific value to search for, so we
        skip keyword filtering for those.  The attribute-index narrowing performed
        before this call already targets chunks that mention the relevant column.

        If no equality predicates exist the whole chunk list is returned unchanged and
        the upstream attribute-index result determines scope.
        """
        if not predicates:
            return chunks

        equality_values: set[str] = set()
        equality_operators = {"="}
        range_operators = {">", "<", ">=", "<=", "!="}

        for predicate in predicates:
            parts = predicate.split()
            if len(parts) >= 3:
                operator = parts[1]
                value = " ".join(parts[2:]).strip("'\"").lower()
                if operator in equality_operators and value:
                    equality_values.add(value)
                # Range predicates: no useful value keyword — skip.

        # If there are no equality values to search for, do not filter.
        if not equality_values:
            return chunks

        filtered = []
        for chunk in chunks:
            content_lower = chunk.content.lower()
            if any(val in content_lower for val in equality_values):
                filtered.append(chunk)

        return filtered
    
    # ========================================================================
    # Query Execution
    # ========================================================================
    


# ============================================================================
# Utility Functions
# ============================================================================

def build_insert_statement(
    table_name: str,
    record: Dict[str, Any]
) -> str:
    """Build SQL INSERT statement."""
    columns = list(record.keys())
    values = list(record.values())
    
    columns_str = ", ".join(columns)
    placeholders = ", ".join(["%s"] * len(values))
    
    sql = f"INSERT INTO {table_name} ({columns_str}) VALUES ({placeholders})"
    
    return sql


def build_update_statement(
    table_name: str,
    record: Dict[str, Any],
    row_id: str
) -> str:
    """Build SQL UPDATE statement."""
    set_clauses = [f"{col} = %s" for col in record.keys()]
    set_str = ", ".join(set_clauses)
    
    sql = f"UPDATE {table_name} SET {set_str} WHERE row_id = '{row_id}'"
    
    return sql
