def format_results_table(
    columns: list[str],
    rows: list[list],
    max_display: int = 50,
) -> str:
    if not columns or not rows:
        return ""

    header = "| " + " | ".join(str(c) for c in columns) + " |"
    separator = "| " + " | ".join("---" for _ in columns) + " |"
    lines = [header, separator]

    display_rows = rows[:max_display]
    for row in display_rows:
        formatted = [str(v) if v is not None else "" for v in row]
        lines.append("| " + " | ".join(formatted) + " |")

    if len(rows) > max_display:
        lines.append("")
        lines.append(f"> Showing {max_display} of {len(rows)} rows.")

    return "\n".join(lines)
