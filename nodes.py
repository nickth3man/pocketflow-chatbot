import logging
import time
from typing import Any

from pocketflow import Node

from utils.attempt_tracker import reset_attempts, track_attempts
from utils.call_llm import call_llm
from utils.call_llm_structured import call_llm_structured
from utils.classify_error import classify_error
from utils.context_trimmer import trim_chat_history
from utils.execute_query import execute_query
from utils.format_response_markdown import format_response_markdown
from utils.format_results_table import format_results_table
from utils.format_schema import format_schema
from utils.get_schema_subset import get_schema_subset
from utils.optimize_sql import optimize_sql
from utils.prompt_cache import get_prompt_cached
from utils.schema_validator import validate_sql_columns
from utils.validate_sql_safety import validate_sql_safety

_logger = logging.getLogger("nba_chatbot")

_VALID_INTENTS = frozenset({"query_db", "chat", "clarify"})

_ERROR_TRUNC_CHARS = 80
_ERROR_EXTRAS_TRUNC_CHARS = 200
_RAW_INPUT_TRUNC_CHARS = 100
_CLEAN_MSG_TRUNC_CHARS = 80
_HISTORY_ENTRY_COUNT = 6
_HISTORY_CONTENT_TRUNC_CHARS = 200
_SQL_TRUNC_CHARS = 500


def _ensure_str(val: Any, sep: str = "\n") -> str:
    if isinstance(val, list):
        return sep.join(str(item) for item in val)
    if val is None:
        return ""
    return str(val)


def _log_step(
    shared: dict[str, Any],
    node_name: str,
    summary: str,
    status: str = "complete",
    extra: dict[str, Any] | None = None,
) -> None:
    _logger.info("[%s] %s", node_name, summary, extra=extra or {})
    entry: dict[str, Any] = {
        "node": node_name,
        "status": status,
        "summary": summary,
    }
    if extra and isinstance(extra, dict):
        entry.update({k: v for k, v in extra.items() if k not in entry})
    shared.setdefault("step_logs", []).append(entry)


def _log_stage(
    shared: dict[str, Any],
    node_name: str,
    stage: str,
    summary: str,
    *,
    elapsed_ms: float = 0,
    status: str = "complete",
    extra: dict[str, Any] | None = None,
) -> None:
    log_extra: dict[str, Any] = {"duration_ms": round(elapsed_ms, 1)}
    if extra:
        log_extra.update(extra)
    label = f"{node_name}.{stage}"
    _logger.info(
        "[%s] %s (%.0fms)",
        label,
        summary,
        elapsed_ms,
        extra=log_extra,
    )


def _append_assistant_turn(
    shared: dict[str, Any],
    content: str,
    sql: str | None = None,
    error: bool = False,
) -> None:
    shared.setdefault("chat_history", []).append({
        "role": "assistant",
        "content": content,
        "sql": sql,
        "error": error,
    })
    shared["chat_history"] = trim_chat_history(shared["chat_history"])


def _run_stage(
    shared: dict[str, Any],
    node_name: str,
    stage: str,
    summary: str,
    fn: Any,
    *args: Any,
    **kwargs: Any,
) -> Any:
    start = time.monotonic()
    try:
        result = fn(*args, **kwargs)
        elapsed = (time.monotonic() - start) * 1000
        _log_stage(shared, node_name, stage, summary, elapsed_ms=elapsed)
        return result
    except Exception as e:
        elapsed = (time.monotonic() - start) * 1000
        _log_stage(
            shared,
            node_name,
            stage,
            f"✗ {str(e)[:_ERROR_TRUNC_CHARS]}",
            elapsed_ms=elapsed,
            status="error",
            extra={"error": str(e)[:_ERROR_EXTRAS_TRUNC_CHARS]},
        )
        raise


# ── Pre-processing Stage ────────────────────────────────────────────────────


class MessagePreprocessorNode(Node):
    NODE_LABEL = "Preprocess"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        raw = shared.get("user_message", "")
        _logger.info(
            "[Preprocess.prep] raw input=%d chars, first 100: %s",
            len(raw),
            raw[:_RAW_INPUT_TRUNC_CHARS],
        )
        return {
            "user_message": raw,
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": get_prompt_cached("preprocess_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[Preprocess.exec] calling LLM to clean message (model=%s)...",
            prep_res.get("model", "?"),
        )
        return call_llm_structured(
            prompt=prep_res["user_message"],
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["clean_message", "entities"],
            system_prompt=prep_res["system_prompt"],
        )

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        clean = _ensure_str(exec_res.get("clean_message", ""))
        entities = exec_res.get("entities", {})
        if not isinstance(entities, dict):
            entities = {}
        shared["clean_message"] = clean
        shared["entities"] = entities
        reset_attempts(shared)
        shared.pop("failed_attempts", None)
        shared.pop("fixed_sql", None)

        entities_summary = (
            ", ".join(f"{k}={v}" for k, v in entities.items() if v) or "none"
        )
        _log_step(
            shared,
            self.NODE_LABEL,
            f"cleaned '{clean[:_CLEAN_MSG_TRUNC_CHARS]}' entities={entities_summary}",
            extra={"clean_chars": len(clean), "entity_keys": list(entities.keys())},
        )
        return "default"


class HistoryContextBuilderNode(Node):
    NODE_LABEL = "HistoryContext"

    def __init__(self) -> None:
        super().__init__(max_retries=1, wait=0)

    def prep(self, shared: dict[str, Any]) -> list[dict[str, Any]]:
        history = shared.get("chat_history", [])
        _logger.debug(
            "[HistoryContext.prep] %d total entries, taking last 6", len(history)
        )
        return history[-_HISTORY_ENTRY_COUNT:]

    def exec(self, prep_res: list[dict[str, Any]]) -> str:
        if not prep_res:
            _logger.debug("[HistoryContext.exec] no history to format")
            return ""
        lines: list[str] = []
        for entry in prep_res:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            sql = entry.get("sql")
            if sql:
                intent = sql.strip()[:80]
                lines.append(
                    f'[{role}: "{content[:_HISTORY_CONTENT_TRUNC_CHARS]}" / SQL: ({intent})]'
                )
            else:
                lines.append(f'[{role}: "{content[:_HISTORY_CONTENT_TRUNC_CHARS]}"]')
        result = "\n".join(lines)
        _logger.debug(
            "[HistoryContext.exec] formatted %d history entries into %d chars",
            len(prep_res),
            len(result),
        )
        return result

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["history_context"] = exec_res
        entry_count = len(prep_res) if prep_res else 0
        _log_step(
            shared,
            self.NODE_LABEL,
            f"{entry_count} history entries → {len(exec_res)} chars",
            extra={"history_entries": entry_count, "history_chars": len(exec_res)},
        )
        return "default"


class IntentClassifierNode(Node):
    NODE_LABEL = "IntentClassifier"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        clean = shared.get("clean_message", "")
        history = shared.get("history_context", "")
        schema_by_table = shared.get("schema_by_table", {})
        available_tables = ", ".join(schema_by_table.keys())
        _logger.debug(
            "[IntentClassifier.prep] clean='%s' history=%d chars tables=%d",
            clean[:60],
            len(history),
            len(schema_by_table),
        )
        return {
            "clean_message": clean,
            "history_context": history,
            "available_tables": available_tables,
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": get_prompt_cached("intent_classifier_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[IntentClassifier.exec] classifying intent (model=%s)...",
            prep_res.get("model", "?"),
        )
        prompt = (
            f"User message: {prep_res['clean_message']}\n\n"
            f"Conversation context:\n{prep_res['history_context']}\n\n"
            f"Available tables in database: {prep_res['available_tables']}"
        )
        return call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["intent", "reason"],
            system_prompt=prep_res["system_prompt"],
        )

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        intent = _ensure_str(exec_res.get("intent", "chat")).strip().lower()
        if intent not in _VALID_INTENTS:
            _logger.warning(
                "[IntentClassifier.post] invalid intent '%s' → defaulting to chat",
                intent,
            )
            intent = "chat"
        shared["intent"] = intent
        reason = _ensure_str(exec_res.get("reason", ""))
        _log_step(
            shared,
            self.NODE_LABEL,
            f"intent={intent} ({reason[:80]})",
            extra={"intent": intent, "reason": reason[:200]},
        )
        return intent


# ── Schema / Planning Stage ─────────────────────────────────────────────────


class TableSelectorNode(Node):
    NODE_LABEL = "TableSelector"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def exec_fallback(self, prep_res: Any, exc: Exception) -> dict[str, Any]:
        schema_by_table = prep_res.get("schema_by_table", {}) if prep_res else {}
        all_tables = list(schema_by_table.keys())
        _logger.warning(
            "[TableSelector] fallback: using all %d tables due to error: %s",
            len(all_tables),
            exc,
        )
        return {
            "tables": all_tables,
            "reason": f"fallback: using all tables due to selection error: {exc}",
        }

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        schema_by_table = shared.get("schema_by_table", {})
        table_listing = "\n".join(f"- {name}" for name in schema_by_table)
        _logger.debug(
            "[TableSelector.prep] %d available tables, entities=%s",
            len(schema_by_table),
            shared.get("entities", {}),
        )
        return {
            "clean_message": shared.get("clean_message", ""),
            "entities": shared.get("entities", {}),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "table_listing": table_listing,
            "schema_by_table": schema_by_table,
            "system_prompt": get_prompt_cached("table_selector_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[TableSelector.exec] selecting tables from %d candidates (model=%s)...",
            len(prep_res.get("schema_by_table", {})),
            prep_res.get("model", "?"),
        )
        prompt = (
            f"User question: {prep_res['clean_message']}\n\n"
            f"Entities: {prep_res['entities']}\n\n"
            f"Available tables:\n{prep_res['table_listing']}"
        )
        return call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["tables", "reason"],
            system_prompt=prep_res["system_prompt"],
        )

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        selected = exec_res["tables"]
        selected = [
            t.get("table", t.get("name", next(iter(t.values()), "")))
            if isinstance(t, dict)
            else str(t)
            for t in selected
        ]
        reason = _ensure_str(exec_res.get("reason", ""))
        schema_by_table = prep_res["schema_by_table"]
        shared["selected_tables"] = selected
        subset = get_schema_subset(schema_by_table, selected)
        schema_text = format_schema(subset)
        shared["schema_context"] = schema_text
        _log_step(
            shared,
            self.NODE_LABEL,
            f"tables={selected} ({len(subset)} tables, {len(schema_text)} schema chars) — {reason[:60]}",
            extra={
                "selected_tables": selected,
                "schema_chars": len(schema_text),
                "table_count": len(selected),
                "reason": reason[:200],
            },
        )
        return "default"


class QueryPlannerNode(Node):
    NODE_LABEL = "QueryPlanner"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def exec_fallback(self, prep_res: Any, exc: Exception) -> dict[str, Any]:
        question = (
            prep_res.get("clean_message", "the user question")
            if prep_res
            else "the user question"
        )
        _logger.warning("[QueryPlanner] fallback plan due to error: %s", exc)
        return {
            "plan": f"Select all relevant columns to answer: {question}",
            "tables_used": prep_res.get("entities", {}) if prep_res else [],
            "filters": [],
            "aggregations": [],
        }

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        schema = shared.get("schema_context", "")
        _logger.debug(
            "[QueryPlanner.prep] schema=%d chars, entities=%s",
            len(schema),
            shared.get("entities", {}),
        )
        return {
            "clean_message": shared.get("clean_message", ""),
            "entities": shared.get("entities", {}),
            "schema_context": schema,
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": get_prompt_cached("query_planner_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[QueryPlanner.exec] planning with %d schema chars (model=%s)...",
            len(prep_res.get("schema_context", "")),
            prep_res.get("model", "?"),
        )
        prompt = (
            f"User question: {prep_res['clean_message']}\n\n"
            f"Entities: {prep_res['entities']}\n\n"
            f"Available schema:\n{prep_res['schema_context']}\n\n"
            f"Conversation context:\n{prep_res['history_context']}"
        )
        return call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["plan", "tables_used", "filters", "aggregations"],
            system_prompt=prep_res["system_prompt"],
        )

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        plan = _ensure_str(exec_res.get("plan", ""))
        tables_used = exec_res.get("tables_used", [])
        filters = exec_res.get("filters", [])
        aggregations = exec_res.get("aggregations", [])
        shared["query_plan"] = plan
        plan_preview = plan[:80].replace("\n", " ")
        _log_step(
            shared,
            self.NODE_LABEL,
            f"plan='{plan_preview}...' tables={tables_used} filters={filters} aggs={aggregations}",
            extra={
                "plan_chars": len(plan),
                "tables_used": tables_used,
                "filters": filters,
                "aggregations": aggregations,
            },
        )
        return "default"


class SQLGeneratorNode(Node):
    NODE_LABEL = "SQLGenerator"

    def __init__(self) -> None:
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        attempts = shared.get("debug_attempts", 0)
        if attempts > 0:
            _logger.info(
                "[SQLGenerator.prep] retry #%d after error recovery — prev error=%s",
                attempts,
                shared.get("execution_error", "")[:100],
            )
        return {
            "clean_message": shared.get("clean_message", ""),
            "schema_context": shared.get("schema_context", ""),
            "query_plan": shared.get("query_plan", ""),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": get_prompt_cached("sql_generator_prompt.txt"),
            "execution_error": shared.get("execution_error"),
            "error_type": shared.get("error_type"),
            "error_analysis": shared.get("error_analysis"),
            "schema_recheck": shared.get("schema_recheck"),
            "debug_attempts": attempts,
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        is_retry = prep_res.get("debug_attempts", 0) > 0
        _logger.info(
            "[SQLGenerator.exec] generating SQL%s (model=%s, plan=%d chars, schema=%d chars)...",
            " [retry]" if is_retry else "",
            prep_res.get("model", "?"),
            len(prep_res.get("query_plan", "")),
            len(prep_res.get("schema_context", "")),
        )

        prompt = (
            f"User question: {prep_res['clean_message']}\n\n"
            f"Schema context:\n{prep_res['schema_context']}\n\n"
            f"Query plan:\n{prep_res['query_plan']}\n\n"
            f"Conversation context:\n{prep_res['history_context']}"
        )

        if is_retry:
            prompt += (
                f"\n\nPREVIOUS ATTEMPT FAILED — error context:\n"
                f"Error: {prep_res['execution_error']}\n"
                f"Error type: {prep_res.get('error_type', 'unknown')}\n"
                f"Error analysis: {prep_res.get('error_analysis', 'N/A')}\n"
                f"Re-checked schema:\n{prep_res.get('schema_recheck', 'N/A')}\n"
                f"\nPlease generate a corrected SQL that fixes the above error."
            )
            _logger.debug(
                "[SQLGenerator.exec] retry context: prev_error=%s, schema_recheck=%d chars",
                (prep_res.get("execution_error") or "")[:80],
                len(prep_res.get("schema_recheck", "") or ""),
            )

        result = call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["thinking", "sql"],
            system_prompt=prep_res["system_prompt"],
        )

        sql = result["sql"]
        _logger.debug("[SQLGenerator.exec] raw SQL (%d chars): %s", len(sql), sql[:120])

        if not sql.strip().upper().startswith(("SELECT", "WITH")):
            raise ValueError(
                f"Generated SQL must start with SELECT or WITH, got: {sql[:50]}"
            )

        is_safe, safety_reason = validate_sql_safety(sql)
        if not is_safe:
            raise ValueError(f"SQL safety check failed: {safety_reason}")
        _logger.debug("[SQLGenerator.exec] safety check passed")

        return sql

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        _logger.warning("[SQLGenerator] fallback after retries: %s", exc)
        return "SELECT 'SQL generation failed after retries' AS error;"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        if exec_res == "SELECT 'SQL generation failed after retries' AS error;":
            error_msg = (
                "I'm sorry, I couldn't generate a valid SQL query for your question. "
                "Please try rephrasing it."
            )
            shared["result_analysis"] = error_msg
            shared["sql_result"] = None
            shared["response_sql"] = None
            shared["generated_sql"] = None
            _append_assistant_turn(shared, content=error_msg, error=True)
            _log_step(
                shared,
                self.NODE_LABEL,
                "SQL generation failed after retries — returning error response to user",
                status="error",
            )
            return "generation_failed"

        optimized = optimize_sql(exec_res)
        if optimized != exec_res:
            _logger.debug(
                "[SQLGenerator.post] optimize_sql modified SQL:\n  before: %s\n  after:  %s",
                exec_res[:80],
                optimized[:80],
            )
        is_safe, safety_reason = validate_sql_safety(optimized)
        if not is_safe:
            raise ValueError(f"Optimized SQL failed safety check: {safety_reason}")
        shared["generated_sql"] = optimized
        shared["execution_error"] = None
        sql_preview = optimized[:120].replace("\n", " ")
        _log_step(
            shared,
            self.NODE_LABEL,
            f"SQL ({len(optimized)} chars): {sql_preview}...",
            extra={
                "sql_chars": len(optimized),
                "sql_full": optimized[:_SQL_TRUNC_CHARS],
                "is_retry": (prep_res.get("debug_attempts", 0) if prep_res else 0) > 0,
            },
        )
        return "default"


# ── Execution Stage ─────────────────────────────────────────────────────────


class SQLExecutorNode(Node):
    NODE_LABEL = "SQLExecutor"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        fixed_sql = shared.get("fixed_sql")
        sql = fixed_sql if fixed_sql else shared.get("generated_sql", "")
        if fixed_sql:
            _logger.info(
                "[SQLExecutor.prep] using fixed_sql from error recovery (%d chars)",
                len(fixed_sql),
            )
        sql_preview = sql[:120].replace("\n", " ")
        _logger.info(
            "[SQLExecutor.prep] sql=%d chars, timeout=%ds, max_rows=%d: %s",
            len(sql),
            shared.get("db_query_timeout", 30),
            shared.get("max_rows", 200),
            sql_preview,
        )
        return {
            "db_path": shared["db_path"],
            "sql": sql,
            "max_rows": shared.get("max_rows", 200),
            "timeout": shared.get("db_query_timeout", 30),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        return execute_query(
            db_path=prep_res["db_path"],
            sql=prep_res["sql"],
            max_rows=prep_res["max_rows"],
            timeout_seconds=prep_res["timeout"],
        )

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        shared.pop("fixed_sql", None)
        if exec_res["success"]:
            shared["sql_result"] = exec_res
            shared["response_sql"] = shared.get("generated_sql", "")
            row_count = len(exec_res.get("rows", []))
            col_count = len(exec_res.get("columns", []))
            elapsed = exec_res.get("elapsed_ms", 0)
            rows_preview = exec_res.get("rows", [])[:3] if row_count else []
            _log_step(
                shared,
                self.NODE_LABEL,
                f"success: {col_count} cols x {row_count} rows ({elapsed:.0f}ms)",
                extra={
                    "columns": col_count,
                    "rows": row_count,
                    "duration_ms": round(elapsed, 1),
                    "sample_rows": len(rows_preview),
                },
            )
            return "success"

        error_msg = exec_res.get("error", "")
        shared["execution_error"] = error_msg
        _log_step(
            shared,
            self.NODE_LABEL,
            f"error: {error_msg[:120]}",
            status="error",
            extra={
                "db_error": error_msg[:300],
                "error_length": len(error_msg),
            },
        )
        return "error"


# ── Error Handling Stage ────────────────────────────────────────────────────


class ErrorAnalyzerNode(Node):
    NODE_LABEL = "ErrorAnalyzer"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def exec_fallback(self, prep_res: Any, exc: Exception) -> dict[str, Any]:
        error_type = prep_res.get("error_type", "unknown") if prep_res else "unknown"
        _logger.warning("[ErrorAnalyzer] fallback analysis due to error: %s", exc)
        return {
            "error_type": error_type,
            "root_cause": "Could not analyze error automatically",
            "affected_entities": [],
            "suggested_fix_direction": "Review the SQL query and schema carefully",
        }

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        shared.pop("sql_result", None)
        error_msg = shared.get("execution_error", "")
        error_type = classify_error(error_msg)
        sql = shared.get("generated_sql", "")
        _logger.info(
            "[ErrorAnalyzer.prep] error='%s' classified_type=%s sql_len=%d",
            error_msg[:100],
            error_type,
            len(sql),
        )
        failed = shared.setdefault("failed_attempts", [])
        failed.append({
            "sql": shared.get("generated_sql", "")[:_SQL_TRUNC_CHARS],
            "error": error_msg[:300],
            "error_type": error_type,
        })
        return {
            "execution_error": error_msg,
            "error_type": error_type,
            "generated_sql": sql,
            "clean_message": shared.get("clean_message", ""),
            "schema_context": shared.get("schema_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[ErrorAnalyzer.exec] analyzing error (model=%s, type=%s)...",
            prep_res.get("model", "?"),
            prep_res.get("error_type", "?"),
        )
        prompt = (
            f"Error: {prep_res['execution_error']}\n\n"
            f"Failed SQL:\n{prep_res['generated_sql']}\n\n"
            f"Original question:\n{prep_res['clean_message']}\n\n"
            f"Schema context:\n{prep_res['schema_context']}"
        )
        system_prompt = get_prompt_cached("error_analyzer_prompt.txt").format(
            error_type=prep_res["error_type"],
            sql=prep_res["generated_sql"],
            question=prep_res["clean_message"],
            schema_context=prep_res["schema_context"],
        )
        return call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=[
                "error_type",
                "root_cause",
                "affected_entities",
                "suggested_fix_direction",
            ],
            system_prompt=system_prompt,
        )

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        error_type = _ensure_str(
            exec_res.get(
                "error_type",
                prep_res.get("error_type", "unknown") if prep_res else "unknown",
            )
        )
        shared["error_type"] = error_type
        shared["error_analysis"] = exec_res
        root_cause = _ensure_str(exec_res.get("root_cause", ""))[:80]
        affected = exec_res.get("affected_entities", [])
        fix_dir = _ensure_str(exec_res.get("suggested_fix_direction", ""))[:80]
        _log_step(
            shared,
            self.NODE_LABEL,
            f"type={error_type} root='{root_cause}' affected={affected} fix='{fix_dir}'",
            extra={
                "error_type": error_type,
                "root_cause": root_cause,
                "affected_entities": affected,
                "fix_direction": fix_dir,
            },
        )
        return "default"


class SchemaRecheckNode(Node):
    NODE_LABEL = "SchemaRecheck"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        error_analysis = shared.get("error_analysis", {})
        affected = error_analysis.get("affected_entities", [])
        _logger.info(
            "[SchemaRecheck.prep] checking %d entities: %s",
            len(affected),
            affected,
        )
        return {
            "affected_entities": affected,
            "schema_by_table": shared.get("schema_by_table", {}),
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        affected = prep_res["affected_entities"]
        schema_by_table = prep_res["schema_by_table"]
        if not affected or all(t == "__nonexistent_table__" for t in affected):
            fallback_tables = list(schema_by_table.keys())[:5]
            _logger.debug(
                "[SchemaRecheck.exec] no valid affected entities, falling back to %s",
                fallback_tables,
            )
            subset = get_schema_subset(schema_by_table, fallback_tables)
            schema_text = format_schema(subset)
            _logger.debug(
                "[SchemaRecheck.exec] re-checked %d tables → %d chars schema",
                len(subset),
                len(schema_text),
            )
            return schema_text
        subset = get_schema_subset(schema_by_table, affected)
        schema_text = format_schema(subset)
        _logger.debug(
            "[SchemaRecheck.exec] re-checked %d tables → %d chars schema",
            len(subset),
            len(schema_text),
        )
        return schema_text

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["schema_recheck"] = exec_res
        pr = prep_res or {}
        affected = pr.get("affected_entities", [])
        _log_step(
            shared,
            self.NODE_LABEL,
            f"re-checked {affected} → {len(exec_res)} schema chars",
            extra={"affected_entities": affected, "recheck_chars": len(exec_res)},
        )
        return "default"


class SQLFixerNode(Node):
    NODE_LABEL = "SQLFixer"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        _logger.warning("[SQLFixer] fallback due to error: %s", exc)
        return (
            prep_res.get("generated_sql", "SELECT 'SQL fix failed' AS error")
            if prep_res
            else "SELECT 'SQL fix failed' AS error"
        )

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        sql = shared.get("generated_sql", "")
        error_type = shared.get("error_type", "")
        _logger.info(
            "[SQLFixer.prep] fixing SQL (%d chars, error=%s)...",
            len(sql),
            error_type,
        )
        return {
            "clean_message": shared.get("clean_message", ""),
            "generated_sql": sql,
            "error_type": error_type,
            "error_analysis": shared.get("error_analysis", {}),
            "schema_recheck": shared.get("schema_recheck", ""),
            "query_plan": shared.get("query_plan", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        _logger.info(
            "[SQLFixer.exec] fixing SQL (model=%s, input_sql=%d chars)...",
            prep_res.get("model", "?"),
            len(prep_res.get("generated_sql", "")),
        )
        prompt = get_prompt_cached("sql_fixer_prompt.txt").format(
            question=prep_res["clean_message"],
            sql=prep_res["generated_sql"],
            error_type=prep_res["error_type"],
            error_analysis=prep_res.get("error_analysis", {}),
            schema_recheck=prep_res["schema_recheck"],
            query_plan=prep_res["query_plan"],
        )
        result = call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["thinking", "sql"],
        )

        sql = result["sql"]
        if not sql.strip().upper().startswith(("SELECT", "WITH")):
            raise ValueError(
                f"Fixed SQL must start with SELECT or WITH, got: {sql[:50]}"
            )

        _logger.debug("[SQLFixer.exec] fixed SQL (%d chars): %s", len(sql), sql[:100])
        return sql

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["fixed_sql"] = exec_res
        sql_preview = exec_res[:100].replace("\n", " ")
        _log_step(
            shared,
            self.NODE_LABEL,
            f"fixed SQL ({len(exec_res)} chars): {sql_preview}...",
            extra={"sql_chars": len(exec_res)},
        )
        return "default"


class FixValidatorNode(Node):
    NODE_LABEL = "FixValidator"

    def prep(self, shared: dict[str, Any]) -> str:
        fixed_sql = shared.get("fixed_sql", "")
        _logger.debug(
            "[FixValidator.prep] validating fixed SQL (%d chars)", len(fixed_sql)
        )
        return fixed_sql

    def exec(self, prep_res: str) -> tuple[bool, str]:
        return validate_sql_safety(prep_res)

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: tuple[bool, str]
    ) -> str:
        is_safe, reason = exec_res
        if is_safe:
            shared["generated_sql"] = shared.get("fixed_sql", "")
        else:
            shared.pop("fixed_sql", None)
        status = "complete" if is_safe else "error"
        _log_step(
            shared,
            self.NODE_LABEL,
            f"safety={'passed' if is_safe else 'failed'}: {reason}",
            status=status,
            extra={"is_safe": is_safe, "reason": reason},
        )
        return "default"


class RecoveryDecisionNode(Node):
    NODE_LABEL = "RecoveryDecision"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        attempts = track_attempts(shared)
        max_attempts = shared.get("max_debug_attempts", 3)
        error_type = shared.get("error_type", "")
        _logger.info(
            "[RecoveryDecision.prep] attempt %d/%d, error_type=%s",
            attempts,
            max_attempts,
            error_type,
        )
        return {
            "debug_attempts": attempts,
            "max_debug_attempts": max_attempts,
            "error_type": error_type,
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        if (
            prep_res["debug_attempts"] < prep_res["max_debug_attempts"]
            and prep_res["error_type"] != "permission"
        ):
            return "retry"
        return "give_up"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["recovery_action"] = exec_res
        pr = prep_res or {}
        attempts = pr.get("debug_attempts", 0)
        max_attempts = pr.get("max_debug_attempts", 3)
        _log_step(
            shared,
            self.NODE_LABEL,
            f"action={exec_res} ({attempts}/{max_attempts})",
            extra={
                "attempt": attempts,
                "max_attempts": max_attempts,
                "action": exec_res,
            },
        )
        return "default"


# ── Response Stage ──────────────────────────────────────────────────────────


class ResultAnalyzerNode(Node):
    NODE_LABEL = "ResultAnalyzer"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        sql_result = shared.get("sql_result")
        has_results = (
            sql_result is not None
            and sql_result.get("success", False)
            and sql_result.get("rows")
        )
        attempts = shared.get("debug_attempts", 0)
        max_attempts = shared.get("max_debug_attempts", 3)
        _logger.info(
            "[ResultAnalyzer.prep] has_results=%s debug=%d/%d",
            has_results,
            attempts,
            max_attempts,
        )
        return {
            "clean_message": shared.get("clean_message", ""),
            "sql_result": sql_result,
            "has_results": has_results,
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "debug_attempts": attempts,
            "max_debug_attempts": max_attempts,
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        system_prompt = get_prompt_cached("result_analyzer_prompt.txt")
        if prep_res["has_results"]:
            sql_result = prep_res["sql_result"]
            table_str = format_results_table(sql_result["columns"], sql_result["rows"])
            elapsed = sql_result.get("elapsed_ms", 0)
            row_count = len(sql_result.get("rows", []))
            col_count = len(sql_result.get("columns", []))
            results_section = f"Query results ({elapsed:.0f}ms):\n\n{table_str}"
            _logger.info(
                "[ResultAnalyzer.exec] narrating %d rows x %d cols (model=%s)...",
                row_count,
                col_count,
                prep_res.get("model", "?"),
            )
        else:
            results_section = (
                "The query could not be completed. "
                f"After {prep_res['debug_attempts']} of {prep_res['max_debug_attempts']} "
                "attempts, the system was unable to generate a valid query. "
                "Please try rephrasing your question."
            )
            _logger.info(
                "[ResultAnalyzer.exec] no results — narrating failure after %d/%d attempts",
                prep_res["debug_attempts"],
                prep_res["max_debug_attempts"],
            )

        prompt = system_prompt.format(
            question=prep_res["clean_message"],
            results_section=results_section,
        )
        return call_llm(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
        )

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        _logger.warning("[ResultAnalyzer] fallback narration due to error: %s", exc)
        return (
            "I wasn't able to analyze the results. Please try rephrasing your question."
        )

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["result_analysis"] = exec_res
        pr = prep_res or {}
        has_results = pr.get("has_results", False)
        _log_step(
            shared,
            self.NODE_LABEL,
            f"narrative generated ({len(exec_res)} chars, has_data={has_results})",
            extra={"narrative_chars": len(exec_res), "has_data": has_results},
        )
        return "default"


class ResponseBuilderNode(Node):
    NODE_LABEL = "ResponseBuilder"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        narrative = shared.get("result_analysis", "")
        sql = shared.get("response_sql")
        _logger.debug(
            "[ResponseBuilder.prep] narrative=%d chars, sql=%s",
            len(narrative),
            f"{len(sql)} chars" if sql else "None",
        )
        return {
            "result_analysis": narrative,
            "sql_result": shared.get("sql_result"),
            "response_sql": sql,
            "debug_attempts": shared.get("debug_attempts", 0),
            "max_debug_attempts": shared.get("max_debug_attempts", 3),
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        narrative = prep_res["result_analysis"]
        sql = prep_res["response_sql"]

        table_md = ""
        elapsed_ms = None
        sql_result = prep_res.get("sql_result")
        if sql_result and sql_result.get("success") and sql_result.get("rows"):
            table_md = format_results_table(sql_result["columns"], sql_result["rows"])
            elapsed_ms = sql_result.get("elapsed_ms")
            row_count = len(sql_result.get("rows", []))
            _logger.debug(
                "[ResponseBuilder.exec] formatting markdown: %d narrative chars + %d-row table",
                len(narrative),
                row_count,
            )

        result = format_response_markdown(
            narrative=narrative,
            table_md=table_md,
            sql=sql,
            elapsed_ms=elapsed_ms,
        )
        _logger.debug("[ResponseBuilder.exec] final markdown=%d chars", len(result))
        return result

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["response"] = exec_res
        has_sql = prep_res.get("response_sql") is not None
        has_error = prep_res.get("sql_result") is None or not prep_res[
            "sql_result"
        ].get("success", False)
        _append_assistant_turn(
            shared,
            content=exec_res,
            sql=prep_res.get("response_sql"),
            error=has_error,
        )
        _log_step(
            shared,
            self.NODE_LABEL,
            f"final response built ({len(exec_res)} chars, sql={has_sql})",
            extra={
                "response_chars": len(exec_res),
                "has_sql": has_sql,
                "has_error": has_error,
            },
        )
        return "default"


# ── SQL Validation Stage ───────────────────────────────────────────────────


class SQLValidatorNode(Node):
    NODE_LABEL = "SQLValidator"

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        sql = shared.get("generated_sql", "")
        _logger.debug("[SQLValidator.prep] validating SQL (%d chars)", len(sql))
        return {
            "generated_sql": sql,
            "db_path": shared["db_path"],
            "schema_by_table": shared.get("schema_by_table", {}),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        sql = prep_res["generated_sql"]
        schema = prep_res["schema_by_table"]
        db_path = prep_res["db_path"]
        _logger.info(
            "[SQLValidator.exec] pre-flight schema check on SQL (%d chars)", len(sql)
        )
        result = validate_sql_columns(sql, schema, db_path)
        return result

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: dict[str, Any]
    ) -> str:
        if exec_res.get("valid"):
            _log_step(shared, self.NODE_LABEL, "schema validation passed")
            return "default"
        errors = exec_res.get("errors", [])
        hints = exec_res.get("hints", [])
        error_summary = "; ".join(errors[:3]) if errors else "unknown validation error"
        _log_step(
            shared,
            self.NODE_LABEL,
            f"validation failed: {error_summary}",
            status="error",
            extra={"errors": errors, "hints": hints},
        )
        shared["validation_errors"] = errors
        shared["validation_hints"] = hints
        shared["execution_error"] = error_summary
        shared["generated_sql"] = shared.get("generated_sql", "")
        return "error"


# ── Chat Stage ──────────────────────────────────────────────────────────────


class ChatResponderNode(Node):
    NODE_LABEL = "ChatResponder"

    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        intent = shared.get("intent", "chat")
        clean = shared.get("clean_message", "")
        _logger.debug(
            "[ChatResponder.prep] intent=%s, message='%s'",
            intent,
            clean[:60],
        )
        return {
            "clean_message": clean,
            "intent": intent,
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        intent = prep_res["intent"]
        _logger.info(
            "[ChatResponder.exec] generating chat response (model=%s, intent=%s)...",
            prep_res.get("model", "?"),
            intent,
        )
        system_prompt = get_prompt_cached("chat_responder_prompt.txt")
        clarify_instruction = ""
        if intent == "clarify":
            clarify_instruction = (
                "\n\nThe user's question is ambiguous. Ask a targeted follow-up "
                "question to clarify what they want (e.g., career stats, recent games, "
                "comparisons, specific seasons)."
            )
            _logger.debug("[ChatResponder.exec] adding clarify instruction")
        prompt = system_prompt.format(clarify_instruction=clarify_instruction)
        return call_llm(
            prompt=prep_res["clean_message"],
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            system_prompt=prompt,
        )

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        _logger.warning("[ChatResponder] fallback due to error: %s", exc)
        return "I'm sorry, I couldn't process that request. Could you try again?"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["response"] = exec_res
        _append_assistant_turn(shared, content=exec_res)
        _log_step(
            shared,
            self.NODE_LABEL,
            f"chat response generated ({len(exec_res)} chars)",
            extra={"response_chars": len(exec_res)},
        )
        return "default"
