from __future__ import annotations

from typing import List, Optional, Tuple

from sqlglot import exp, parse_one


def add_missing_aliases_for_join(sql: str) -> Tuple[str, List[str]]:
    """
    For join queries, ensure qualified columns have explicit aliases so duckdb keeps
    the `table.column` prefix in the output.
    Returns the patched SQL and a list of added alias names.
    """
    expr = parse_one(sql, error_level="ignore")
    added: List[str] = []

    if expr is None:
        return sql, added

    table_names = {table.name for table in expr.find_all(exp.Table)}
    if len(table_names) <= 1:
        return sql, added

    if not hasattr(expr, "selects") or not expr.selects:
        return sql, added

    new_selects = []
    for select_expr in expr.selects:
        column = _extract_column(select_expr)
        if column and column.table and not _has_explicit_alias(select_expr):
            alias = f"{column.table}.{column.name}"
            new_selects.append(exp.alias_(select_expr, alias, quoted=True))
            added.append(alias)
        else:
            new_selects.append(select_expr)

    if not added:
        return sql, added

    expr.set("expressions", new_selects)
    return expr.sql(dialect="duckdb"), added


def _extract_column(expr: exp.Expression) -> Optional[exp.Column]:
    if isinstance(expr, exp.Alias):
        expr = expr.this
    if isinstance(expr, exp.Column):
        return expr
    return None


def _has_explicit_alias(expr: exp.Expression) -> bool:
    if isinstance(expr, exp.Alias):
        return True
    alias = expr.args.get("alias")
    return alias is not None
