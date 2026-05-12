import contextlib
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

import duckdb

_DEFAULT_MEMORY_LIMIT = "2GB"

_logger = logging.getLogger("nba_chatbot")

_EXECUTOR = ThreadPoolExecutor(max_workers=1)
_connections: dict[str, duckdb.DuckDBPyConnection] = {}
_connections_lock = threading.Lock()


def _get_connection(db_path: str) -> duckdb.DuckDBPyConnection:
    with _connections_lock:
        con = _connections.get(db_path)
        if con is not None:
            return con
        con = duckdb.connect(db_path, read_only=True)
        con.execute(f"SET memory_limit = '{_DEFAULT_MEMORY_LIMIT}'")
        _connections[db_path] = con
        return con


def _close_connection() -> None:
    global _connections
    with _connections_lock:
        for con in _connections.values():
            with contextlib.suppress(Exception):
                con.close()
        _connections = {}


def _run_query(
    db_path: str, sql: str, max_rows: int
) -> tuple[list[str], list[list[Any]], float]:
    start = time.time()
    con = _get_connection(db_path)
    result = con.execute(sql)
    columns = [desc[0] for desc in result.description]
    raw_rows = result.fetchmany(max_rows)
    rows = [list(row) for row in raw_rows]
    elapsed_ms = (time.time() - start) * 1000
    return columns, rows, elapsed_ms


def execute_query(
    db_path: str,
    sql: str,
    max_rows: int = 200,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    start = time.time()

    stripped = sql.strip()
    operation = stripped.split(None, 1)[0].upper() if stripped else "UNKNOWN"
    sql_preview = stripped[:120].replace("\n", " ")

    _logger.debug(
        "[DB] submitting %s query (%d chars) to pool...",
        operation,
        len(stripped),
    )

    future = _EXECUTOR.submit(_run_query, db_path, sql, max_rows)
    try:
        columns, rows, elapsed_ms = future.result(timeout=timeout_seconds)
        row_count = len(rows)

        _logger.info(
            "[DB] %s (%d cols x %d rows, %.0fms): %s",
            operation,
            len(columns),
            row_count,
            elapsed_ms,
            sql_preview,
            extra={
                "db_operation": operation,
                "db_sql_chars": len(stripped),
                "db_duration_ms": round(elapsed_ms, 1),
                "db_columns": len(columns),
                "db_row_count": row_count,
                "db_success": True,
                "duration_ms": round(elapsed_ms, 1),
                "success": True,
            },
        )

        return {
            "success": True,
            "columns": columns,
            "rows": rows,
            "elapsed_ms": elapsed_ms,
            "error": None,
        }
    except FuturesTimeoutError:
        elapsed_ms = (time.time() - start) * 1000
        _logger.warning(
            "[DB] %s ✗ timed out after %ds (%d chars): %s",
            operation,
            timeout_seconds,
            len(stripped),
            sql_preview,
            extra={
                "db_operation": operation,
                "db_duration_ms": round(elapsed_ms, 1),
                "db_success": False,
                "db_error": f"timeout after {timeout_seconds}s",
                "duration_ms": round(elapsed_ms, 1),
                "success": False,
            },
        )
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "elapsed_ms": elapsed_ms,
            "error": f"Query timed out after {timeout_seconds} seconds",
        }
    except duckdb.Error as e:
        elapsed_ms = (time.time() - start) * 1000
        error_str = str(e)
        _logger.warning(
            "[DB] %s ✗ DuckDB error after %.0fms: %s",
            operation,
            elapsed_ms,
            error_str[:200],
            extra={
                "db_operation": operation,
                "db_duration_ms": round(elapsed_ms, 1),
                "db_success": False,
                "db_error": error_str[:200],
                "duration_ms": round(elapsed_ms, 1),
                "success": False,
            },
        )
        return {
            "success": False,
            "columns": [],
            "rows": [],
            "elapsed_ms": elapsed_ms,
            "error": error_str,
        }
