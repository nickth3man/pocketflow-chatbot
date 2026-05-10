import duckdb


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
                f"SELECT column_name, data_type FROM information_schema.columns "
                f"WHERE table_name = '{table_name}' AND table_schema = 'main' "
                f"ORDER BY ordinal_position"
            ).fetchall()

            count_row = con.execute(f'SELECT count(*) FROM "{table_name}"').fetchone()
            row_count = count_row[0] if count_row else 0

            schema_by_table[table_name] = {
                "type": table_type,
                "columns": [{"name": col[0], "type": col[1]} for col in columns],
                "row_count": row_count,
            }

        return schema_by_table
    finally:
        con.close()
