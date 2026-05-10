import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import duckdb


def _run_query(
    db_path: str, sql: str, max_rows: int
) -> tuple[list[str], list[list], float]:
    start = time.time()
    con = duckdb.connect(db_path, read_only=True)
    try:
        con.execute("SET memory_limit = '2GB'")
        result = con.execute(sql)
        columns = [desc[0] for desc in result.description]
        raw_rows = result.fetchmany(max_rows)
        rows = [list(row) for row in raw_rows]
        elapsed_ms = (time.time() - start) * 1000
        return columns, rows, elapsed_ms
    finally:
        con.close()


def execute_query(
    db_path: str,
    sql: str,
    max_rows: int = 200,
    timeout_seconds: int = 30,
) -> dict:
    start = time.time()

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(_run_query, db_path, sql, max_rows)
        try:
            columns, rows, elapsed_ms = future.result(timeout=timeout_seconds)
            return {
                "success": True,
                "columns": columns,
                "rows": rows,
                "elapsed_ms": elapsed_ms,
                "error": None,
            }
        except TimeoutError:
            elapsed_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "elapsed_ms": elapsed_ms,
                "error": f"Query timed out after {timeout_seconds} seconds",
            }
        except duckdb.Error as e:
            elapsed_ms = (time.time() - start) * 1000
            return {
                "success": False,
                "columns": [],
                "rows": [],
                "elapsed_ms": elapsed_ms,
                "error": str(e),
            }
