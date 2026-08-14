from __future__ import annotations

from pathlib import Path
from typing import Dict, Mapping, Optional

import duckdb
import pandas as pd

from .config import EvalSettings
from .logging_utils import setup_logger
from .semantic_join import SemanticJoinExecutor
from .sql_parser import ParsedQuery
from .utils import clean_string_columns, drop_unnamed_columns, normalize_types, standardize_column_name


class GtRunner:
    """Register GT CSVs into duckdb and execute SQL."""

    def __init__(self, gt_dir: Path, attributes: Mapping, logger_name: str = "gt_runner") -> None:
        self.gt_dir = Path(gt_dir)
        self.attributes = attributes
        self.logger = setup_logger(logger_name)
        self.conn = duckdb.connect(database=":memory:")
        self._tables_loaded = False
        self._table_cache: Dict[str, pd.DataFrame] = {}

    def _load_tables(self) -> None:
        for csv_path in sorted(self.gt_dir.glob("*.csv")):
            table = csv_path.stem
            df = pd.read_csv(csv_path)
            df = drop_unnamed_columns(df)
            df = clean_string_columns(df)
            df = normalize_types(df, self.attributes)
            self.conn.register(table, df)
            self._table_cache[table] = df
            self.logger.debug("Registered table %s from %s", table, csv_path)
        self._tables_loaded = True

    def run(
        self,
        sql: str,
        parsed_query: Optional[ParsedQuery] = None,
        settings: Optional[EvalSettings] = None,
    ) -> pd.DataFrame:
        if not self._tables_loaded:
            self._load_tables()

        if settings and settings.semantic_join_enabled and parsed_query and parsed_query.query_type == "join":
            try:
                return self._run_with_semantic_join(sql, parsed_query, settings)
            except Exception as exc:  # pragma: no cover - fallback safety
                self.logger.warning("Semantic join execution failed, fallback to exact join: %s", exc)

        self.logger.info("Running SQL on GT (exact)")
        df = self.conn.execute(sql).fetchdf()
        return self._post_process(df)

    def _run_with_semantic_join(
        self, sql: str, parsed_query: ParsedQuery, settings: EvalSettings
    ) -> pd.DataFrame:
        self.logger.info("Running SQL on GT with semantic join enabled")
        filtered_tables = self._prepare_filtered_tables(parsed_query)
        executor = SemanticJoinExecutor(settings=settings, attributes=self.attributes, logger_name="semantic_join")
        augmented_tables = executor.augment_tables(parsed_query, filtered_tables)

        conn = duckdb.connect(database=":memory:")
        for table, df in augmented_tables.items():
            conn.register(table, df)
        df = conn.execute(sql).fetchdf()
        return self._post_process(df)

    def _prepare_filtered_tables(self, parsed_query: ParsedQuery) -> Dict[str, pd.DataFrame]:
        if not parsed_query.tables:
            return dict(self._table_cache)

        result: Dict[str, pd.DataFrame] = {}
        table_filters = parsed_query.table_filters or {}
        for table in parsed_query.tables:
            base = self._table_cache.get(table)
            if base is None:
                continue
            filter_clause = table_filters.get(table)
            if filter_clause:
                try:
                    query = f"SELECT * FROM {table} WHERE {filter_clause}"
                    filtered = self.conn.execute(query).fetchdf()
                except Exception as exc:  # pragma: no cover - defensive
                    self.logger.warning(
                        "Failed to apply filter '%s' on table %s, fallback to full table: %s",
                        filter_clause,
                        table,
                        exc,
                    )
                    filtered = base.copy()
            else:
                filtered = base.copy()
            result[table] = filtered
        return result

    def _post_process(self, df: pd.DataFrame) -> pd.DataFrame:
        renamed = {col: standardize_column_name(col) for col in df.columns}
        df = df.rename(columns=renamed)
        df = clean_string_columns(df)
        return df
