def format_schema(schema_subset: dict) -> str:
    lines: list[str] = []
    for table_name, info in schema_subset.items():
        columns = info.get("columns", [])
        col_strs = [f"{c['name']} {c['type']}" for c in columns]
        lines.append(f"TABLE {table_name} ({', '.join(col_strs)})")
    return "\n".join(lines)
