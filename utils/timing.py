import functools
import logging
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any

_logger = logging.getLogger("nba_chatbot")


@contextmanager
def timed_operation(
    operation_name: str,
    *,
    logger: logging.Logger | None = None,
    level: int = logging.DEBUG,
    extra: dict[str, Any] | None = None,
) -> Generator[dict[str, Any], None, None]:
    log = logger or _logger
    start = time.monotonic()
    info: dict[str, Any] = {"elapsed_ms": 0, "success": True}
    try:
        yield info
    except Exception as e:
        info["success"] = False
        info["error"] = str(e)
        info["error_type"] = type(e).__name__
        elapsed = (time.monotonic() - start) * 1000
        info["elapsed_ms"] = elapsed
        log_extra: dict[str, Any] = {
            "timing_op": operation_name,
            "duration_ms": round(elapsed, 1),
            "success": False,
        }
        if extra:
            log_extra.update(extra)
        log.log(
            level if info["success"] else logging.WARNING,
            "[Timing] %s failed after %.1fms — %s: %s",
            operation_name,
            elapsed,
            info["error_type"],
            info.get("error", ""),
            extra=log_extra,
        )
        raise
    else:
        elapsed = (time.monotonic() - start) * 1000
        info["elapsed_ms"] = elapsed
        log_extra = {
            "timing_op": operation_name,
            "duration_ms": round(elapsed, 1),
            "success": True,
        }
        if extra:
            log_extra.update(extra)
        log.log(
            level,
            "[Timing] %s completed in %.1fms",
            operation_name,
            elapsed,
            extra=log_extra,
        )


def timed_func(name: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            label = name or getattr(func, "__name__", "unknown")
            with timed_operation(label):
                return func(*args, **kwargs)

        return wrapper

    return decorator
