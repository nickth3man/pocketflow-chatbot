def format_response_markdown(
    narrative: str,
    table_md: str,
    sql: str | None,
    elapsed_ms: float | None,
) -> str:
    parts = [narrative.strip()]

    if table_md:
        parts.append("")
        parts.append(table_md.strip())

    if sql:
        elapsed_str = f"{elapsed_ms:.0f}ms" if elapsed_ms is not None else "N/A"
        details = (
            "<details>\n"
            f"<summary>View SQL ({elapsed_str})</summary>\n\n"
            f"```sql\n{sql.strip()}\n```\n"
            "</details>"
        )
        parts.append("")
        parts.append(details)

    return "\n\n".join(parts).strip()
