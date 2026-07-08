"""
Workload Lattice Planner for WDIRS.
Implements MQO (Multi-Query Optimization) and semantic type identification.
"""

import json
import logging
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
import re

import sqlglot
from sqlglot import parse_one, exp

from config import SEMANTIC_TYPES, OLLAMA_MODEL, OLLAMA_URL

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class ColumnInfo:
    """Information about a column in the workload."""
    table_name: str
    column_name: str
    semantic_type: str = "OTHER"
    predicates: Set[str] = field(default_factory=set)
    # Raw literal values seen in equality predicates across the whole workload.
    # e.g. WHERE country = 'USA' AND country = 'Canada'  →  {'USA', 'Canada'}
    # These are used as normalization hints during extraction so the LLM stores
    # values in exactly the form the queries expect.
    predicate_literals: Set[str] = field(default_factory=set)
    is_join_key: bool = False
    is_group_by: bool = False
    is_aggregated: bool = False

@dataclass
class TableInfo:
    """Information about a table in the workload."""
    table_name: str
    columns: Dict[str, ColumnInfo] = field(default_factory=dict)
    predicates: List[str] = field(default_factory=list)
    referenced_in_joins: bool = False

@dataclass
class WorkloadLattice:
    """Represents the lattice of extraction objectives."""
    tables: Dict[str, TableInfo] = field(default_factory=dict)
    join_pairs: List[Tuple[str, str]] = field(default_factory=list)
    # Full column-level join info: (left_table, left_col, right_table, right_col)
    join_column_pairs: List[Tuple[str, str, str, str]] = field(default_factory=list)
    subsumption_graph: Dict[str, List[str]] = field(default_factory=dict)


# ============================================================================
# Workload Lattice Planner
# ============================================================================

class LatticePlanner:
    """
    Analyzes SQL workload to build extraction lattice.
    Implements MQO to minimize redundant LLM calls.
    """
    
    def __init__(self, llm_client=None):
        """Initialize planner with optional LLM client."""
        self.llm_client = llm_client
        self.lattice = WorkloadLattice()
    
    def parse_workload(
        self,
        sql_queries: List[str],
        identify_types: bool = True
    ) -> WorkloadLattice:
        """
        Parse SQL workload and build lattice.

        Args:
            sql_queries: List of SQL query strings
            identify_types: If True (default), call the LLM to classify column
                semantic types.  Pass False when restoring the lattice in Phase 2
                (tables already exist in DB, type info is not needed for SQL exec).

        Returns:
            WorkloadLattice with all tables, columns, and predicates
        """
        logger.info(f"Parsing workload with {len(sql_queries)} queries")

        # Reset lattice so we don't accumulate stale state on restore
        self.lattice = WorkloadLattice()

        for query_idx, query in enumerate(sql_queries):
            try:
                self._parse_query(query, query_idx)
            except Exception as e:
                logger.warning(f"Failed to parse query {query_idx}: {e}")
                logger.debug(f"Query: {query}")

        # Build subsumption graph
        self._build_subsumption_graph()

        if identify_types:
            self._identify_semantic_types()
        else:
            logger.info("Skipping LLM semantic type identification (restore mode)")

        logger.info(f"Parsed workload: {len(self.lattice.tables)} tables, "
                   f"{sum(len(t.columns) for t in self.lattice.tables.values())} columns")

        return self.lattice
    
    def _parse_query(self, query: str, query_idx: int) -> None:
        """Parse a single SQL query and update lattice."""
        try:
            # Parse SQL using sqlglot
            parsed = parse_one(query, dialect="postgres")
            
            # Extract tables
            tables = self._extract_tables(parsed)
            
            # Extract columns
            columns = self._extract_columns(parsed)
            
            # Extract predicates
            predicates = self._extract_predicates(parsed)
            
            # Extract joins
            joins = self._extract_joins(parsed)
            
            # Update lattice
            for table_name in tables:
                if table_name not in self.lattice.tables:
                    self.lattice.tables[table_name] = TableInfo(table_name=table_name)
            
            # Add columns to tables
            for table_name, col_name in columns:
                if table_name not in self.lattice.tables:
                    self.lattice.tables[table_name] = TableInfo(table_name=table_name)
                
                table_info = self.lattice.tables[table_name]
                
                if col_name not in table_info.columns:
                    table_info.columns[col_name] = ColumnInfo(
                        table_name=table_name,
                        column_name=col_name
                    )
            
            # Add predicates
            for table_name, col_name, predicate in predicates:
                if table_name in self.lattice.tables:
                    table_info = self.lattice.tables[table_name]
                    
                    if col_name in table_info.columns:
                        table_info.columns[col_name].predicates.add(predicate)
                    
                    table_info.predicates.append(predicate)
            
            # Add joins
            for lt, lc, rt, rc in joins:
                if (lt, rt) not in self.lattice.join_pairs:
                    self.lattice.join_pairs.append((lt, rt))
                if lc and rc and (lt, lc, rt, rc) not in self.lattice.join_column_pairs:
                    self.lattice.join_column_pairs.append((lt, lc, rt, rc))

                # Mark tables as referenced in joins
                if lt in self.lattice.tables:
                    self.lattice.tables[lt].referenced_in_joins = True
                if rt in self.lattice.tables:
                    self.lattice.tables[rt].referenced_in_joins = True
            
            # Identify aggregations and group by
            self._extract_aggregations(parsed)
            
        except Exception as e:
            logger.error(f"Error parsing query {query_idx}: {e}")
            raise
    
    # -------------------------------------------------------------------------
    # Alias resolution helpers
    # -------------------------------------------------------------------------

    def _build_alias_map(self, parsed: exp.Expression) -> Dict[str, str]:
        """Return a mapping of alias (or bare table name) → real table name.

        Handles every table source that can appear in a FROM/JOIN:
          - Plain table:          FROM player          → {'player': 'player'}
          - Aliased table:        FROM player p        → {'p': 'player', 'player': 'player'}
          - All join types:       JOIN team t ON …     → {'t': 'team', 'team': 'team'}
          - Sub-selects are
            intentionally skipped (no real table to map to).
        """
        alias_map: Dict[str, str] = {}
        for table_expr in parsed.find_all(exp.Table):
            real = table_expr.name
            if not real:
                continue
            real_lower = real.lower()
            alias_node = table_expr.args.get("alias")
            alias = alias_node.name.lower() if alias_node and alias_node.name else None
            # Always register the real name as a self-alias
            alias_map[real_lower] = real_lower
            if alias and alias != real_lower:
                alias_map[alias] = real_lower
        return alias_map

    def _resolve_table(
        self,
        raw: Optional[str],
        alias_map: Dict[str, str],
        primary_table: Optional[str],
    ) -> Optional[str]:
        """Resolve a raw table/alias token to the real table name."""
        if raw:
            return alias_map.get(raw.lower(), raw.lower())
        return primary_table

    # -------------------------------------------------------------------------
    # Table / column / predicate / join extraction
    # -------------------------------------------------------------------------

    def _extract_tables(self, parsed: exp.Expression) -> Set[str]:
        """Extract real table names from parsed query (all join types)."""
        return set(self._build_alias_map(parsed).values())

    def _extract_columns(self, parsed: exp.Expression) -> List[Tuple[str, str]]:
        """Extract (real_table, column) pairs from a parsed query.

        Three sources are considered:
          1. SELECT projections
          2. WHERE-clause columns
          3. ON-clause columns in every JOIN (join-key columns must be in
             the schema so they can be extracted and aligned)

        An alias map is built first so every qualified reference like ``p.name``
        is resolved to ``(player, name)`` and unqualified columns fall back to
        the FROM table (single-table queries) or are attributed per-source.
        """
        alias_map = self._build_alias_map(parsed)
        # Primary table = the FROM table (first real table in alias map values
        # that appears in the FROM clause, not a JOIN).
        primary_table: Optional[str] = None
        from_clause = parsed.args.get("from")
        if from_clause:
            for t in from_clause.find_all(exp.Table):
                if t.name:
                    primary_table = alias_map.get(t.name.lower(), t.name.lower())
                    break

        columns: List[Tuple[str, str]] = []
        seen: set = set()

        def _add(tbl: Optional[str], col: str) -> None:
            resolved = self._resolve_table(tbl, alias_map, primary_table)
            if resolved and col:
                key = (resolved, col.lower())
                if key not in seen:
                    seen.add(key)
                    columns.append(key)

        # 1. SELECT projections
        for select in parsed.find_all(exp.Select):
            for projection in select.expressions:
                if isinstance(projection, exp.Alias):
                    inner = projection.this
                    if isinstance(inner, exp.Column):
                        _add(inner.table or None, inner.name)
                elif isinstance(projection, exp.Column):
                    _add(projection.table or None, projection.name)
                # exp.Star → skip (extract all columns from text)

        # 2. WHERE clause
        for where in parsed.find_all(exp.Where):
            for col in where.find_all(exp.Column):
                _add(col.table or None, col.name)

        # 3. ON-clause join-key columns (all join types: INNER, LEFT, RIGHT,
        #    FULL OUTER, CROSS). These must be in the schema so the extractor
        #    knows to pull them and entity resolution can align them.
        for join in parsed.find_all(exp.Join):
            on_expr = join.args.get("on")
            if on_expr is not None:
                for col in on_expr.find_all(exp.Column):
                    _add(col.table or None, col.name)

        # 4. Columns inside aggregation functions (SUM/AVG/MIN/MAX/COUNT).
        #    These are often the only occurrence of a column (e.g.
        #    "SELECT AVG(age) FROM owner" has no mention of `age` elsewhere).
        #    They must be in the schema so _extract_aggregations can mark them
        #    as QUANTITY and the extractor knows to request a numeric value.
        for agg in parsed.find_all(exp.Sum, exp.Avg, exp.Min, exp.Max, exp.Count):
            for col in agg.find_all(exp.Column):
                _add(col.table or None, col.name)

        return columns

    def _extract_predicates(
        self,
        parsed: exp.Expression
    ) -> List[Tuple[str, str, str]]:
        """
        Extract predicates from WHERE clause.
        Returns: List of (real_table, column, predicate_string)
        """
        predicates = []

        alias_map = self._build_alias_map(parsed)
        primary_table: Optional[str] = None
        from_clause = parsed.args.get("from")
        if from_clause:
            for t in from_clause.find_all(exp.Table):
                if t.name:
                    primary_table = alias_map.get(t.name.lower(), t.name.lower())
                    break

        for where in parsed.find_all(exp.Where):
            for comparison in where.find_all(exp.EQ, exp.GT, exp.LT, exp.GTE, exp.LTE, exp.NEQ):
                left = comparison.left
                right = comparison.right

                if isinstance(left, exp.Column):
                    table = self._resolve_table(left.table or None, alias_map, primary_table)
                    column = left.name

                    if table and column:
                        operator = self._get_operator(comparison)
                        value = self._get_value(right)

                        predicate = f"{column} {operator} {value}"
                        predicates.append((table.lower(), column.lower(), predicate))

                        # For equality predicates, record the raw literal so
                        # the extractor can normalize extracted values to match.
                        if isinstance(comparison, exp.EQ) and isinstance(right, exp.Literal):
                            literal_val = right.this
                            tbl_entry = self.lattice.tables.get(table.lower())
                            if tbl_entry is not None:
                                col_info = tbl_entry.columns.get(column.lower())
                                if col_info is not None:
                                    col_info.predicate_literals.add(literal_val)

        return predicates

    def _get_operator(self, comparison: exp.Expression) -> str:
        """Get operator string from comparison expression."""
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
        else:
            return "="
    
    def _get_value(self, expr: exp.Expression) -> str:
        """Extract value from expression."""
        if isinstance(expr, exp.Literal):
            return expr.this
        elif isinstance(expr, exp.Column):
            return expr.name
        else:
            return str(expr)
    
    def _extract_joins(self, parsed: exp.Expression) -> List[Tuple[str, str, str, str]]:
        """Extract join column pairs from query ON/USING clauses.

        Handles all join types (INNER, LEFT, RIGHT, FULL OUTER, CROSS).
        Returns list of (real_left_table, left_col, real_right_table, right_col).
        Falls back to table-only pairs when columns cannot be determined.
        """
        alias_map = self._build_alias_map(parsed)
        joins: List[Tuple[str, str, str, str]] = []

        # Determine the left-hand (FROM) table for each join.  For the first
        # JOIN the FROM table is the left side; for subsequent JOINs it is the
        # right-side table of the previous JOIN in the chain.
        from_clause = parsed.args.get("from")
        left_table_for_next: Optional[str] = None
        if from_clause:
            for t in from_clause.find_all(exp.Table):
                if t.name:
                    left_table_for_next = alias_map.get(t.name.lower(), t.name.lower())
                    break

        for join in parsed.find_all(exp.Join):
            # Resolve the right-side (joined) table
            right_real: Optional[str] = None
            for t in join.find_all(exp.Table):
                if t.name:
                    right_real = alias_map.get(t.name.lower(), t.name.lower())
                    break

            on_expr = join.args.get("on")
            using_expr = join.args.get("using")

            found_column_pair = False

            if on_expr is not None:
                # ON col1 = col2  (possibly via aliases)
                for eq in on_expr.find_all(exp.EQ):
                    left_col_node = eq.left
                    right_col_node = eq.right
                    if isinstance(left_col_node, exp.Column) and isinstance(right_col_node, exp.Column):
                        lt = self._resolve_table(
                            left_col_node.table or None, alias_map, left_table_for_next
                        )
                        lc = left_col_node.name.lower()
                        rt = self._resolve_table(
                            right_col_node.table or None, alias_map, right_real
                        )
                        rc = right_col_node.name.lower()
                        if lt and rt and lc and rc:
                            joins.append((lt, lc, rt, rc))
                            found_column_pair = True

            elif using_expr is not None:
                # USING (col) — same column name on both sides
                for col in using_expr.find_all(exp.Column):
                    col_name = col.name.lower()
                    if left_table_for_next and right_real and col_name:
                        joins.append((left_table_for_next, col_name, right_real, col_name))
                        found_column_pair = True

            if not found_column_pair and left_table_for_next and right_real:
                # Fallback: record table-pair without column info
                joins.append((left_table_for_next, "", right_real, ""))

            # The right side becomes the left side for the next JOIN in the chain
            if right_real:
                left_table_for_next = right_real

        return joins
    
    def _extract_aggregations(self, parsed: exp.Expression) -> None:
        """Identify aggregated columns and group by columns."""
        alias_map = self._build_alias_map(parsed)

        # Aggregation functions
        for agg in parsed.find_all(exp.Count, exp.Sum, exp.Avg, exp.Min, exp.Max):
            for column in agg.find_all(exp.Column):
                table = self._resolve_table(column.table or None, alias_map, None)
                col_name = column.name

                if table and col_name and table in self.lattice.tables:
                    col_info = self.lattice.tables[table].columns.get(col_name.lower())
                    if col_info is not None:
                        col_info.is_aggregated = True
                        # SUM/AVG/MIN/MAX always imply a numeric column.
                        # Promote to QUANTITY when the heuristic left it as OTHER
                        # so the extractor knows to request a JSON number.
                        if not isinstance(agg, exp.Count) and col_info.semantic_type == "OTHER":
                            # Aggregated numeric columns default to QUANTITY.
                            # QUANTITY_COUNT is determined by the LLM based on column name,
                            # table context, and workload predicates.
                            col_info.semantic_type = "QUANTITY"

        # GROUP BY columns
        for group_by in parsed.find_all(exp.Group):
            for column in group_by.find_all(exp.Column):
                table = self._resolve_table(column.table or None, alias_map, None)
                col_name = column.name

                if table and col_name and table in self.lattice.tables:
                    col_info = self.lattice.tables[table].columns.get(col_name.lower())
                    if col_info is not None:
                        col_info.is_group_by = True
    
    def _build_subsumption_graph(self) -> None:
        """
        Build subsumption graph to identify redundant extraction objectives.
        If Q1 filters on 'Status' and Q2 filters on 'Status', merge them.
        """
        logger.info("Building subsumption graph")
        
        # For each table, group columns by their predicates
        for table_name, table_info in self.lattice.tables.items():
            column_groups = defaultdict(list)
            
            for col_name, col_info in table_info.columns.items():
                # Group by predicate set
                pred_key = frozenset(col_info.predicates)
                column_groups[pred_key].append(col_name)
            
            # Build subsumption relationships
            for pred_key, columns in column_groups.items():
                if len(columns) > 1:
                    # These columns can be extracted together
                    base_col = columns[0]
                    self.lattice.subsumption_graph[f"{table_name}.{base_col}"] = [
                        f"{table_name}.{col}" for col in columns[1:]
                    ]
        
        logger.info(f"Built subsumption graph with {len(self.lattice.subsumption_graph)} groups")
    
    def _identify_semantic_types(self) -> None:
        """
        Identify semantic types for columns using LLM.
        Uses simple heuristics if LLM is not available.
        """
        logger.info("Identifying semantic types")
        
        for table_name, table_info in self.lattice.tables.items():
            for col_name, col_info in table_info.columns.items():
                # We previously used string-matching heuristics here, but that is
                # domain-overfitting (e.g. hardcoding 'price' -> MONEY).
                # Instead, we rely entirely on the LLM to infer the semantic type
                # from the column name, table context, and observed workload predicates.
                if self.llm_client:
                    semantic_type = self._llm_semantic_type(
                        col_name,
                        table_name,
                        workload_predicates=list(col_info.predicates),
                    )
                else:
                    semantic_type = "OTHER"
                
                col_info.semantic_type = semantic_type
        
        logger.info("Semantic type identification complete")
    
    def _llm_semantic_type(
        self,
        column_name: str,
        table_name: str,
        workload_predicates: Optional[List[str]] = None,
    ) -> str:
        """
        Use LLM to identify semantic type.

        workload_predicates: predicate strings observed in the training SQL for
        this column (e.g. ["price > 1000", "status = 'ACTIVE'"]). These give
        the LLM concrete evidence about the column's value domain.
        """
        if not self.llm_client:
            return "OTHER"
        
        try:
            predicate_section = ""
            if workload_predicates:
                examples = ", ".join(f'"{p}"' for p in sorted(workload_predicates)[:6])
                predicate_section = (
                    f"\nWorkload predicate examples for this column: {examples}\n"
                    f"(Use these value comparisons as evidence about the column's domain "
                    f"and typical magnitude.)\n"
                )

            prompt = f"""Given a database column name, its table, and (optionally) workload \
predicate examples, identify the most appropriate semantic type.

Column: {column_name}
Table: {table_name}{predicate_section}
Semantic types:
- PERSON: Names of people
- ORG: Organizations, companies, institutions
- DATE: Dates, times, timestamps, years
- GPE: Locations, cities, countries
- CODE: Identifiers, codes, IDs, ticker symbols
- MONEY: Monetary values, prices, costs
- QUANTITY: General numeric measures (e.g. population, area, temperature, dosage, weight)
- QUANTITY_COUNT: Cumulative count or tally of discrete events/items (e.g. number of transactions, \
number of occurrences, number of completed tasks)
- PRODUCT: Products, items, goods
- EVENT: Events, activities, occurrences
- OTHER: Anything that does not fit the above

Key distinction — QUANTITY vs QUANTITY_COUNT:
  QUANTITY: General numeric measurements.
  QUANTITY_COUNT: Tallies of how many times something discrete happened.

Please use the provided workload predicate examples (if any) as additional context \
to help determine the semantic type.

Respond with only the semantic type label (one word, uppercase).
"""
            
            response = self.llm_client.generate(prompt, max_tokens=10, temperature=0.0)
            semantic_type = response.strip().upper()
            
            if semantic_type in SEMANTIC_TYPES:
                return semantic_type
            else:
                return "OTHER"
        
        except Exception as e:
            logger.warning(f"LLM semantic type identification failed: {e}")
            return "OTHER"
    
    # ========================================================================
    # Query Methods
    # ========================================================================
    
    def get_extraction_plan(self) -> Dict[str, Any]:
        """
        Generate extraction plan from lattice.
        Returns a structured plan for extraction.
        """
        plan = {
            "tables": {},
            "join_pairs": self.lattice.join_pairs,
            "join_column_pairs": self.lattice.join_column_pairs,
            "subsumption_groups": self.lattice.subsumption_graph
        }
        
        for table_name, table_info in self.lattice.tables.items():
            plan["tables"][table_name] = {
                "columns": {},
                "predicates": table_info.predicates,
                "referenced_in_joins": table_info.referenced_in_joins
            }
            
            for col_name, col_info in table_info.columns.items():
                plan["tables"][table_name]["columns"][col_name] = {
                    "semantic_type": col_info.semantic_type,
                    "predicates": list(col_info.predicates),
                    "is_join_key": col_info.is_join_key,
                    "is_group_by": col_info.is_group_by,
                    "is_aggregated": col_info.is_aggregated
                }
        
        return plan
    
    def get_table_schema(self, table_name: str) -> Dict[str, str]:
        """
        Get schema for a table (column -> semantic_type mapping).
        """
        if table_name not in self.lattice.tables:
            return {}
        
        table_info = self.lattice.tables[table_name]
        schema = {}
        
        for col_name, col_info in table_info.columns.items():
            # Aggregated columns (SUM/AVG/MIN/MAX) are always numeric.
            # Fall back to QUANTITY for aggregated columns still typed as OTHER.
            sem = col_info.semantic_type
            if col_info.is_aggregated and sem == "OTHER":
                sem = "QUANTITY"
            schema[col_name] = sem
        
        return schema
    
    def get_required_columns(self, table_name: str) -> List[str]:
        """Get list of required columns for a table."""
        if table_name not in self.lattice.tables:
            return []
        
        return list(self.lattice.tables[table_name].columns.keys())
    
    def get_predicates_for_column(
        self,
        table_name: str,
        column_name: str
    ) -> Set[str]:
        """Get all predicates for a specific column."""
        if table_name not in self.lattice.tables:
            return set()
        
        table_info = self.lattice.tables[table_name]
        if column_name not in table_info.columns:
            return set()
        
        return table_info.columns[column_name].predicates

    def get_predicate_literals(
        self,
        table_name: str,
        column_name: str
    ) -> Set[str]:
        """
        Return the set of raw equality-predicate literal values for a column.
        e.g. if queries have WHERE country = 'USA' and WHERE country = 'Canada'
        this returns {'USA', 'Canada'}.
        """
        if table_name not in self.lattice.tables:
            return set()
        table_info = self.lattice.tables[table_name]
        if column_name not in table_info.columns:
            return set()
        return table_info.columns[column_name].predicate_literals

    def get_normalization_hints(self, table_name: str) -> Dict[str, List[str]]:
        """
        Build a column → [expected literal values] map for all columns in a table
        that have equality predicates in the workload.  Used by the extractor to
        guide value normalization at extraction time.
        """
        if table_name not in self.lattice.tables:
            return {}
        hints: Dict[str, List[str]] = {}
        for col_name, col_info in self.lattice.tables[table_name].columns.items():
            if col_info.predicate_literals:
                hints[col_name] = sorted(col_info.predicate_literals)
        return hints
    
    def should_extract_together(
        self,
        table_name: str,
        columns: List[str]
    ) -> bool:
        """
        Check if columns should be extracted together based on subsumption.
        """
        # Check if any column is in subsumption graph
        for col in columns:
            key = f"{table_name}.{col}"
            if key in self.lattice.subsumption_graph:
                return True
        
        return False


# ============================================================================
# Workload Parser Utilities
# ============================================================================

def parse_sql_file(file_path: str) -> List[str]:
    """
    Parse SQL file and extract individual queries.
    Handles comments and multi-line queries.
    """
    with open(file_path, 'r') as f:
        content = f.read()
    
    # Remove comments
    content = re.sub(r'--.*$', '', content, flags=re.MULTILINE)
    content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
    
    # Split by semicolon
    queries = [q.strip() for q in content.split(';') if q.strip()]
    
    return queries


def load_workload_from_directory(directory: str) -> List[str]:
    """
    Load all SQL queries from a directory.
    """
    import os
    from pathlib import Path
    
    queries = []
    dir_path = Path(directory)
    
    for sql_file in dir_path.glob("**/*.sql"):
        file_queries = parse_sql_file(str(sql_file))
        queries.extend(file_queries)
    
    logger.info(f"Loaded {len(queries)} queries from {directory}")
    
    return queries
