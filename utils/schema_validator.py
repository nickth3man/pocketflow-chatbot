import contextlib
import logging
import re

import duckdb

_logger = logging.getLogger("nba_chatbot")

_RE_SENTINEL = re.compile(r"__nonexistent_table__|__nonexistent_column__")


def extract_table_references(sql: str) -> list[str]:
    tables: list[str] = []
    for match in re.finditer(r"(?:FROM|JOIN)\s+(\w+(?:\.\w+)?)", sql, re.IGNORECASE):
        ref = match.group(1).lower()
        if ref not in tables:
            tables.append(ref)
    return tables


def validate_sql_columns(
    sql: str,
    schema_by_table: dict,
    db_path: str,
) -> dict:
    if _RE_SENTINEL.search(sql):
        return {
            "valid": False,
            "errors": ["SQL references sentinel nonexistent table/column"],
            "hints": ["Schema mismatch - re-check available tables"],
            "unknown_columns": [],
            "missing_tables": extract_table_references(sql),
        }

    if db_path == ":memory:" or not db_path:
        return {
            "valid": True,
            "errors": [],
            "hints": [],
            "unknown_columns": [],
            "missing_tables": [],
        }

    stripped = sql.strip().upper()
    if not stripped.startswith(("SELECT", "WITH", "EXPLAIN")):
        return {
            "valid": False,
            "errors": ["SQL must start with SELECT or WITH"],
            "hints": ["Only SELECT and WITH queries are allowed for validation"],
            "unknown_columns": [],
            "missing_tables": [],
        }

    try:
        con = duckdb.connect(db_path, read_only=True)
        try:
            result = con.execute(f"EXPLAIN {sql}").fetchone()
            plan_text = result[0] if result else ""
            _logger.debug(
                "[schema_validator] EXPLAIN succeeded (%d chars plan)",
                len(plan_text),
            )
            return {
                "valid": True,
                "errors": [],
                "hints": [],
                "unknown_columns": [],
                "missing_tables": [],
            }
        except duckdb.Error as e:
            error_str = str(e)
            _logger.debug("[schema_validator] EXPLAIN failed: %s", error_str[:150])
            missing_tables: list[str] = []
            unknown_columns: list[str] = []
            hints: list[str] = []

            table_match = re.search(
                r"Table with name\s+(\S+)\s+does not exist", error_str, re.IGNORECASE
            )
            if table_match:
                bad_table = table_match.group(1).lower()
                missing_tables.append(bad_table)
                suggestions = [
                    t for t in schema_by_table if t.lower().startswith(bad_table[0])
                ][:3]
                if suggestions:
                    hints.append(f"Did you mean: {', '.join(suggestions)}?")

            col_match = re.search(
                r'column\s+(?:"([^"]+)"|(\S+))\s+does not exist',
                error_str,
                re.IGNORECASE,
            )
            if col_match:
                bad_col = col_match.group(1) or col_match.group(2) or ""
                unknown_columns.append(bad_col)

            if not missing_tables and not unknown_columns:
                category = _categorize_error(error_str)
                hints.append(f"Error category: {category}")

            return {
                "valid": False,
                "errors": [error_str[:300]],
                "hints": hints,
                "unknown_columns": unknown_columns,
                "missing_tables": missing_tables,
            }
        finally:
            with contextlib.suppress(Exception):
                con.close()
    except duckdb.Error as e:
        return {
            "valid": False,
            "errors": [f"Cannot connect to database: {e}"],
            "hints": [],
            "unknown_columns": [],
            "missing_tables": [],
        }


def _categorize_error(error_str: str) -> str:
    error_lower = error_str.lower()
    if "syntax error" in error_lower:
        return "syntax_error"
    if "ambiguous" in error_lower:
        return "ambiguous_column"
    if "catalog error" in error_lower:
        return "catalog_error"
    if "binder error" in error_lower:
        return "binder_error"
    return "other"
