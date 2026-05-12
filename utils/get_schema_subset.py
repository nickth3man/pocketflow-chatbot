from typing import Any


def get_schema_subset(
    schema_by_table: dict[str, Any],
    table_names: list[str | dict[str, str]],
) -> dict[str, Any]:
    result = {}
    for name in table_names:
        # LLM sometimes returns dicts (e.g. {table: x, column: y}) instead of strings
        if isinstance(name, dict):
            for candidate in name.values():
                if isinstance(candidate, str) and candidate in schema_by_table:
                    result[candidate] = schema_by_table[candidate]
        elif isinstance(name, str) and name in schema_by_table:
            result[name] = schema_by_table[name]
    return result
