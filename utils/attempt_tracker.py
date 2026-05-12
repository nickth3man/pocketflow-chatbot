import logging
from typing import Any

_logger = logging.getLogger("nba_chatbot")


class MaxAttemptsExceeded(Exception):
    pass


def track_attempts(
    shared: dict[str, Any],
    key: str = "debug_attempts",
    max_key: str = "max_debug_attempts",
    default_max: int = 3,
) -> int:
    shared.setdefault(key, 0)
    shared[key] += 1
    shared.setdefault(max_key, default_max)
    current = shared[key]
    maximum = shared[max_key]
    _logger.debug("[attempt_tracker] %s = %d/%d", key, current, maximum)
    return current


def check_attempts(
    shared: dict[str, Any],
    key: str = "debug_attempts",
    max_key: str = "max_debug_attempts",
) -> bool:
    current = shared.get(key, 0)
    maximum = shared.get(max_key, 3)
    return current < maximum


def reset_attempts(
    shared: dict[str, Any],
    key: str = "debug_attempts",
    max_key: str = "max_debug_attempts",
) -> None:
    shared[key] = 0
    shared[max_key] = 3
