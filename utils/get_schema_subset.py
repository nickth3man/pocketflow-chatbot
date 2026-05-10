def get_schema_subset(
    schema_by_table: dict,
    table_names: list[str],
) -> dict:
    return {
        name: schema_by_table[name] for name in table_names if name in schema_by_table
    }
