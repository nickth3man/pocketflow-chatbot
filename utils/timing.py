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
        log.log(
            level if info["success"] else logging.WARNING,
            "[Timing] %s failed after %.1fms — %s: %s",
            operation_name,
            elapsed,
            info["error_type"],
            info.get("error", ""),
            extra={"timing_op": operation_name, "duration_ms": round(elapsed, 1), "success": False},
        )
        raise
    else:
        elapsed = (time.monotonic() - start) * 1000
        info["elapsed_ms"] = elapsed
        log.log(
            level,
            "[Timing] %s completed in %.1fms",
            operation_name,
            elapsed,
            extra={"timing_op": operation_name, "duration_ms": round(elapsed, 1), "success": True},
        )


def timed_func(name: str | None = None) -> Callable:
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            label = name or func.__name__
            with timed_operation(label):
                return func(*args, **kwargs)
        return wrapper
    return decorator


def log_llm_call(
    logger: logging.Logger,
    prompt_preview: str,
    response_preview: str,
    elapsed_ms: float,
    *,
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    attempt: int = 1,
    success: bool = True,
    error: str = "",
) -> None:
    extra = {
        "llm_model": model,
        "llm_prompt_chars": len(prompt_preview),
        "llm_response_chars": len(response_preview),
        "llm_duration_ms": round(elapsed_ms, 1),
        "llm_attempt": attempt,
        "llm_success": success,
    }
    if prompt_tokens:
        extra["llm_prompt_tokens"] = prompt_tokens
    if completion_tokens:
        extra["llm_completion_tokens"] = completion_tokens
    if total_tokens:
        extra["llm_total_tokens"] = total_tokens
    if error:
        extra["llm_error"] = error

    if success:
        logger.info(
            "[LLM] %s → %s chars in %.0fms (attempt %d)",
            model or "?",
            len(response_preview),
            elapsed_ms,
            attempt,
            extra=extra,
        )
    else:
        logger.warning(
            "[LLM] %s ✗ failed after %.0fms (attempt %d): %s",
            model or "?",
            elapsed_ms,
            attempt,
            error[:120],
            extra=extra,
        )


def log_db_query(
    logger: logging.Logger,
    sql_preview: str,
    elapsed_ms: float,
    *,
    row_count: int = 0,
    success: bool = True,
    error: str = "",
    operation: str = "SELECT",
) -> None:
    extra = {
        "db_operation": operation,
        "db_sql_chars": len(sql_preview),
        "db_duration_ms": round(elapsed_ms, 1),
        "db_row_count": row_count,
        "db_success": success,
    }
    if error:
        extra["db_error"] = error[:200]

    if success:
        logger.info(
            "[DB] %s (%d rows) in %.0fms",
            sql_preview[:100],
            row_count,
            elapsed_ms,
            extra=extra,
        )
    else:
        logger.warning(
            "[DB] ✗ %s failed after %.0fms: %s",
            sql_preview[:100],
            elapsed_ms,
            error[:120],
            extra=extra,
        )
