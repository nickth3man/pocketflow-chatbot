import duckdb

_SAMPLE_PATTERNS = (
    "season",
    "type",
    "abbrev",
    "status",
    "position",
    "period",
    "action",
    "country",
    "league",
    "city",
    "name",
    "starting_position",
)

_MAX_ENUM_CARDINALITY = 30


def _should_sample(col_name: str) -> bool:
    name_lower = col_name.lower()
    return any(p in name_lower for p in _SAMPLE_PATTERNS)


def _fetch_samples(con, table_name: str, col_name: str) -> list[str] | None:
    try:
        row = con.execute(
            f'SELECT COUNT(DISTINCT "{col_name}") FROM "{table_name}"'
        ).fetchone()
        if row is None:
            return None
        distinct_count = row[0]
        if distinct_count == 0:
            return None
        if distinct_count <= _MAX_ENUM_CARDINALITY:
            rows = con.execute(
                f'SELECT DISTINCT "{col_name}" FROM "{table_name}" '
                f'WHERE "{col_name}" IS NOT NULL ORDER BY "{col_name}" LIMIT {_MAX_ENUM_CARDINALITY}'
            ).fetchall()
        else:
            rows = con.execute(
                f'SELECT DISTINCT "{col_name}" FROM "{table_name}" '
                f'WHERE "{col_name}" IS NOT NULL LIMIT 5'
            ).fetchall()
        return [str(r[0]) for r in rows if r[0] is not None]
    except Exception:
        return None


def get_full_schema(db_path: str) -> dict:
    con = duckdb.connect(db_path, read_only=True)
    try:
        tables = con.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_schema = 'main'"
        ).fetchall()

        schema_by_table: dict = {}
        for table_name, table_type in tables:
            columns = con.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = ? AND table_schema = 'main' "
                "ORDER BY ordinal_position",
                [table_name],
            ).fetchall()

            count_row = con.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()
            row_count = count_row[0] if count_row else 0

            col_defs = []
            for col_name, col_type in columns:
                col_def: dict = {"name": col_name, "type": col_type}
                is_varchar = col_type.upper() in (
                    "VARCHAR",
                    "TEXT",
                    "CHARACTER VARYING",
                    "STRING",
                ) or col_type.upper().startswith("VARCHAR")
                if is_varchar and _should_sample(col_name):
                    samples = _fetch_samples(con, table_name, col_name)
                    if samples:
                        col_def["samples"] = samples
                col_defs.append(col_def)

            schema_by_table[table_name] = {
                "type": table_type,
                "columns": col_defs,
                "row_count": row_count,
            }

        return schema_by_table
    finally:
        con.close()
