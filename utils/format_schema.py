from typing import Any


def format_schema(schema_subset: dict[str, Any]) -> str:
    lines: list[str] = []
    for table_name, info in schema_subset.items():
        columns = info.get("columns", [])
        row_count = info.get("row_count", 0)
        col_strs: list[str] = []
        for c in columns:
            col_str = f"{c.get('name', '?')} {c.get('type', '?')}"
            samples = c.get("samples")
            if samples:
                sample_display = ", ".join(f"'{s}'" for s in samples[:8])
                if len(samples) > 8:
                    sample_display += ", ..."
                col_str += f" [values: {sample_display}]"
            col_strs.append(col_str)
        lines.append(
            f"TABLE {table_name} ({row_count:,} rows):\n  " + "\n  ".join(col_strs)
        )
    return "\n\n".join(lines)
