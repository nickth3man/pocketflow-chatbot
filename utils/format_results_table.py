from typing import Any


def format_results_table(
    columns: list[str],
    rows: list[list[Any]],
    max_display: int = 50,
) -> str:
    if not columns or not rows:
        return ""

    sep = " | "
    header = "| " + sep.join(columns) + " |"
    separator = "| " + sep.join(["---"] * len(columns)) + " |"
    out: list[str] = [header, separator]
    trunc = len(rows) > max_display
    limit = max_display if trunc else len(rows)
    append = out.append

    for row_index in range(limit):
        row = rows[row_index]
        append("| " + sep.join(str(v) if v is not None else "" for v in row) + " |")

    if trunc:
        append("")
        append(f"> Showing {max_display} of {len(rows)} rows.")

    return "\n".join(out)
