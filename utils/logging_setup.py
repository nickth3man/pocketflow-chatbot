import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

_LOGGING_CONFIGURED = False


class DurationFormatter(logging.Formatter):
    """Formatter that appends structured duration info when available."""

    def _get_attr(self, record: logging.LogRecord, name: str) -> Any:
        return getattr(record, name, None)

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        parts: list[str] = [base]

        dur = self._get_attr(record, "duration_ms")
        if dur is not None:
            parts.append(f"⏱{dur}ms")

        token_count = self._get_attr(record, "llm_total_tokens")
        if token_count is not None:
            parts.append(f"tok={token_count}")

        row_count = self._get_attr(record, "db_row_count")
        if row_count is not None:
            parts.append(f"rows={row_count}")

        success = self._get_attr(record, "success")
        if success is not None:
            parts.append("✓" if success else "✗")

        return " | ".join(parts)


def setup_logging(prefix: str = "run") -> logging.Logger:
    global _LOGGING_CONFIGURED
    logger = logging.getLogger("nba_chatbot")

    if _LOGGING_CONFIGURED:
        return logger
    _LOGGING_CONFIGURED = True

    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setLevel(logging.INFO)
    console.setFormatter(
        DurationFormatter(
            "[%(asctime)s] %(levelname)-5s %(name)s - %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    logger.addHandler(console)

    log_dir = Path(__file__).resolve().parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"{prefix}_{timestamp}.log"
    file_handler = logging.FileHandler(str(log_file), mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(
        DurationFormatter(
            "[%(asctime)s] %(levelname)-5s %(name)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger("nba_chatbot")
