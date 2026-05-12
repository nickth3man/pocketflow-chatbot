import logging
from typing import Any

_logger = logging.getLogger("nba_chatbot")


def trim_chat_history(
    entries: list[dict[str, Any]], max_chars: int = 4000
) -> list[dict[str, Any]]:
    if not entries:
        return []
    total = sum(len(str(e.get("content", ""))) for e in entries)
    if total <= max_chars:
        return entries
    trimmed: list[dict[str, Any]] = []
    running = 0
    for entry in reversed(entries):
        char_count = len(str(entry.get("content", "")))
        if running + char_count > max_chars:
            break
        trimmed.insert(0, entry)
        running += char_count
    if not trimmed:
        trimmed = [entries[-1]]
    _logger.debug(
        "[context_trimmer] chat history trimmed: %d → %d entries (%d → %d chars)",
        len(entries),
        len(trimmed),
        total,
        running,
    )
    return trimmed


def trim_schema_context(schema_text: str, max_chars: int = 3000) -> str:
    if not schema_text or len(schema_text) <= max_chars:
        return schema_text
    lines = schema_text.split("\n")
    result: list[str] = []
    running = 0
    for line in lines:
        line_len = len(line) + 1
        if running + line_len > max_chars:
            remaining = len(lines) - len(result)
            result.append(f"... ({remaining} more tables/columns omitted)")
            break
        result.append(line)
        running += line_len
    _logger.debug(
        "[context_trimmer] schema trimmed: %d → %d chars",
        len(schema_text),
        running,
    )
    return "\n".join(result)
