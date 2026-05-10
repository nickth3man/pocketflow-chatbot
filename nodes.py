import logging
from pathlib import Path
from typing import Any

from pocketflow import Node

from utils.call_llm import call_llm
from utils.call_llm_structured import call_llm_structured
from utils.classify_error import classify_error
from utils.execute_query import execute_query
from utils.format_response_markdown import format_response_markdown
from utils.format_results_table import format_results_table
from utils.format_schema import format_schema
from utils.get_schema_subset import get_schema_subset
from utils.optimize_sql import optimize_sql
from utils.validate_sql_safety import validate_sql_safety

PROMPTS_DIR = Path(__file__).parent / "prompts"

_logger = logging.getLogger("nba_chatbot")


def _load_prompt(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def _log_step(
    shared: dict[str, Any],
    node_name: str,
    summary: str,
    status: str = "complete",
) -> None:
    _logger.info("[%s] %s", node_name, summary)
    shared.setdefault("step_logs", []).append({
        "node": node_name,
        "status": status,
        "summary": summary,
    })


# ── Pre-processing Stage ────────────────────────────────────────────────────


class MessagePreprocessorNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[MessagePreprocessor] prep: input=%s", shared.get("user_message", "")[:60]
        )
        return {
            "user_message": shared["user_message"],
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": _load_prompt("preprocess_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info("[MessagePreprocessor] exec: calling LLM to clean message...")
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
        shared["clean_message"] = exec_res["clean_message"]
        shared["entities"] = exec_res["entities"]
        entities_summary = (
            ", ".join(f"{k}={v}" for k, v in exec_res.get("entities", {}).items() if v)
            or "none"
        )
        _log_step(shared, "Preprocess", f"cleaned, entities: {entities_summary}")
        return "default"


class HistoryContextBuilderNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=1, wait=0)

    def prep(self, shared: dict[str, Any]) -> list[dict[str, Any]]:
        return shared.get("chat_history", [])[-6:]

    def exec(self, prep_res: list[dict[str, Any]]) -> str:
        if not prep_res:
            return ""
        lines: list[str] = []
        for entry in prep_res:
            role = entry.get("role", "unknown")
            content = entry.get("content", "")
            sql = entry.get("sql")
            if sql:
                intent = sql.strip()[:80]
                lines.append(f'[{role}: "{content[:200]}" / SQL: ({intent})]')
            else:
                lines.append(f'[{role}: "{content[:200]}"]')
        return "\n".join(lines)

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["history_context"] = exec_res
        entry_count = len(prep_res) if prep_res else 0
        _log_step(shared, "HistoryContext", f"{entry_count} history entries formatted")
        return "default"


class IntentClassifierNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "clean_message": shared.get("clean_message", ""),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": _load_prompt("intent_classifier_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info("[IntentClassifier] exec: classifying intent...")
        prompt = (
            f"User message: {prep_res['clean_message']}\n\n"
            f"Conversation context:\n{prep_res['history_context']}"
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
        intent = exec_res["intent"]
        shared["intent"] = intent
        shared["debug_attempts"] = 0
        shared["max_debug_attempts"] = 3
        reason = exec_res.get("reason", "")
        _log_step(shared, "IntentClassifier", f"intent={intent} ({reason[:60]})")
        return intent


# ── Schema / Planning Stage ─────────────────────────────────────────────────


class TableSelectorNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        schema_by_table = shared.get("schema_by_table", {})
        table_listing = "\n".join(f"- {name}" for name in schema_by_table)
        return {
            "clean_message": shared.get("clean_message", ""),
            "entities": shared.get("entities", {}),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "table_listing": table_listing,
            "schema_by_table": schema_by_table,
            "system_prompt": _load_prompt("table_selector_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info("[TableSelector] exec: selecting relevant tables...")
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
        selected_tables = exec_res["tables"]
        schema_by_table = prep_res["schema_by_table"]
        shared["selected_tables"] = selected_tables
        subset = get_schema_subset(schema_by_table, selected_tables)
        shared["schema_context"] = format_schema(subset)
        _log_step(shared, "TableSelector", f"tables={selected_tables}")
        return "default"


class QueryPlannerNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "clean_message": shared.get("clean_message", ""),
            "entities": shared.get("entities", {}),
            "schema_context": shared.get("schema_context", ""),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": _load_prompt("query_planner_prompt.txt"),
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        _logger.info("[QueryPlanner] exec: planning query...")
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
        shared["query_plan"] = exec_res["plan"]
        plan_preview = exec_res["plan"][:60].replace("\n", " ")
        _log_step(shared, "QueryPlanner", f"plan: {plan_preview}...")
        return "default"


class SQLGeneratorNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=3, wait=2)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "clean_message": shared.get("clean_message", ""),
            "schema_context": shared.get("schema_context", ""),
            "query_plan": shared.get("query_plan", ""),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "system_prompt": _load_prompt("sql_generator_prompt.txt"),
            "execution_error": shared.get("execution_error"),
            "error_type": shared.get("error_type"),
            "error_analysis": shared.get("error_analysis"),
            "schema_recheck": shared.get("schema_recheck"),
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        prompt = (
            f"User question: {prep_res['clean_message']}\n\n"
            f"Schema context:\n{prep_res['schema_context']}\n\n"
            f"Query plan:\n{prep_res['query_plan']}\n\n"
            f"Conversation context:\n{prep_res['history_context']}"
        )

        if prep_res.get("execution_error"):
            prompt += (
                f"\n\nPREVIOUS ATTEMPT FAILED — error context:\n"
                f"Error: {prep_res['execution_error']}\n"
                f"Error type: {prep_res.get('error_type', 'unknown')}\n"
                f"Error analysis: {prep_res.get('error_analysis', 'N/A')}\n"
                f"Re-checked schema:\n{prep_res.get('schema_recheck', 'N/A')}\n"
                f"\nPlease generate a corrected SQL that fixes the above error."
            )

        result = call_llm_structured(
            prompt=prompt,
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            required_fields=["thinking", "sql"],
            system_prompt=prep_res["system_prompt"],
        )

        sql = result["sql"]
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("Generated SQL must start with SELECT")

        is_safe, reason = validate_sql_safety(sql)
        if not is_safe:
            raise ValueError(f"SQL safety check failed: {reason}")

        return sql

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        return "SELECT 'SQL generation failed after retries' AS error"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        optimized = optimize_sql(exec_res)
        shared["generated_sql"] = optimized
        shared["execution_error"] = None
        sql_preview = optimized[:80].replace("\n", " ")
        _log_step(shared, "SQLGenerator", f"SQL: {sql_preview}...")
        return "default"


# ── Execution Stage ─────────────────────────────────────────────────────────


class SQLExecutorNode(Node):
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        _logger.info(
            "[SQLExecutor] prep: executing SQL (%d chars)...",
            len(shared.get("generated_sql", "")),
        )
        return {
            "db_path": shared["db_path"],
            "sql": shared["generated_sql"],
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
        if exec_res["success"]:
            shared["sql_result"] = exec_res
            shared["response_sql"] = shared.get("generated_sql", "")
            row_count = len(exec_res.get("rows", []))
            elapsed = exec_res.get("elapsed_ms", 0)
            _log_step(
                shared, "SQLExecutor", f"success ({row_count} rows, {elapsed:.0f}ms)"
            )
            return "success"

        shared["execution_error"] = exec_res["error"]
        _log_step(
            shared,
            "SQLExecutor",
            f"error: {exec_res.get('error', '')[:80]}",
            status="error",
        )
        return "error"


# ── Error Handling Stage ────────────────────────────────────────────────────


class ErrorAnalyzerNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        error_msg = shared.get("execution_error", "")
        error_type = classify_error(error_msg)
        return {
            "execution_error": error_msg,
            "error_type": error_type,
            "generated_sql": shared.get("generated_sql", ""),
            "clean_message": shared.get("clean_message", ""),
            "schema_context": shared.get("schema_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
        }

    def exec(self, prep_res: dict[str, Any]) -> dict[str, Any]:
        prompt = f"Error: {prep_res['execution_error']}\n\nFailed SQL:\n{prep_res['generated_sql']}\n\nOriginal question:\n{prep_res['clean_message']}\n\nSchema context:\n{prep_res['schema_context']}"
        system_prompt = _load_prompt("error_analyzer_prompt.txt").format(
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
        shared["error_type"] = prep_res["error_type"]
        shared["error_analysis"] = exec_res
        root_cause = exec_res.get("root_cause", "")[:80]
        _log_step(
            shared,
            "ErrorAnalyzer",
            f"type={prep_res['error_type']}, root: {root_cause}",
        )
        return "default"


class SchemaRecheckNode(Node):
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        error_analysis = shared.get("error_analysis", {})
        affected = error_analysis.get("affected_entities", [])
        schema_by_table = shared.get("schema_by_table", {})
        return {
            "affected_entities": affected,
            "schema_by_table": schema_by_table,
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        affected = prep_res["affected_entities"]
        schema_by_table = prep_res["schema_by_table"]
        if not affected:
            return ""
        subset = get_schema_subset(schema_by_table, affected)
        return format_schema(subset)

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["schema_recheck"] = exec_res
        pr = prep_res or {}
        affected = pr.get("affected_entities", [])
        _log_step(shared, "SchemaRecheck", f"re-checked {affected}")
        return "default"


class SQLFixerNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "clean_message": shared.get("clean_message", ""),
            "generated_sql": shared.get("generated_sql", ""),
            "error_type": shared.get("error_type", ""),
            "error_analysis": shared.get("error_analysis", {}),
            "schema_recheck": shared.get("schema_recheck", ""),
            "query_plan": shared.get("query_plan", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        prompt = _load_prompt("sql_fixer_prompt.txt").format(
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
        if not sql.strip().upper().startswith("SELECT"):
            raise ValueError("Fixed SQL must start with SELECT")

        return sql

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["fixed_sql"] = exec_res
        sql_preview = exec_res[:80].replace("\n", " ")
        _log_step(shared, "SQLFixer", f"fixed SQL: {sql_preview}...")
        return "default"


class FixValidatorNode(Node):
    def prep(self, shared: dict[str, Any]) -> str:
        return shared.get("fixed_sql", "")

    def exec(self, prep_res: str) -> tuple[bool, str]:
        return validate_sql_safety(prep_res)

    def post(
        self, shared: dict[str, Any], prep_res: Any, exec_res: tuple[bool, str]
    ) -> str:
        is_safe, reason = exec_res
        if is_safe:
            shared["generated_sql"] = shared.get("fixed_sql", "")
        status = "complete" if is_safe else "error"
        _log_step(
            shared,
            "FixValidator",
            f"safety={'passed' if is_safe else 'failed'}: {reason}",
            status=status,
        )
        return "default"


class RecoveryDecisionNode(Node):
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        attempts = shared.get("debug_attempts", 0) + 1
        shared["debug_attempts"] = attempts
        return {
            "debug_attempts": attempts,
            "max_debug_attempts": shared.get("max_debug_attempts", 3),
            "error_type": shared.get("error_type", ""),
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
            shared, "RecoveryDecision", f"action={exec_res} ({attempts}/{max_attempts})"
        )
        return "default"


# ── Response Stage ──────────────────────────────────────────────────────────


class ResultAnalyzerNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        sql_result = shared.get("sql_result")
        has_results = (
            sql_result is not None
            and sql_result.get("success", False)
            and sql_result.get("rows")
        )
        return {
            "clean_message": shared.get("clean_message", ""),
            "sql_result": sql_result,
            "has_results": has_results,
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
            "debug_attempts": shared.get("debug_attempts", 0),
            "max_debug_attempts": shared.get("max_debug_attempts", 3),
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        system_prompt = _load_prompt("result_analyzer_prompt.txt")
        if prep_res["has_results"]:
            sql_result = prep_res["sql_result"]
            table_str = format_results_table(sql_result["columns"], sql_result["rows"])
            elapsed = sql_result.get("elapsed_ms", 0)
            results_section = f"Query results ({elapsed:.0f}ms):\n\n{table_str}"
        else:
            results_section = (
                "The query could not be completed. "
                f"After {prep_res['debug_attempts']} of {prep_res['max_debug_attempts']} "
                "attempts, the system was unable to generate a valid query. "
                "Please try rephrasing your question."
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
        return (
            "I wasn't able to analyze the results. Please try rephrasing your question."
        )

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["result_analysis"] = exec_res
        pr = prep_res or {}
        has_results = pr.get("has_results", False)
        _log_step(
            shared, "ResultAnalyzer", f"narrative generated (has_data={has_results})"
        )
        return "default"


class ResponseBuilderNode(Node):
    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "result_analysis": shared.get("result_analysis", ""),
            "sql_result": shared.get("sql_result"),
            "response_sql": shared.get("response_sql"),
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

        return format_response_markdown(
            narrative=narrative,
            table_md=table_md,
            sql=sql,
            elapsed_ms=elapsed_ms,
        )

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["response"] = exec_res
        chat_history: list = shared.setdefault("chat_history", [])
        chat_history.append({
            "role": "assistant",
            "content": exec_res,
            "sql": prep_res.get("response_sql"),
            "error": prep_res.get("sql_result") is None
            or not prep_res["sql_result"].get("success", False),
        })
        _log_step(shared, "ResponseBuilder", "final response built")
        return "default"


# ── Chat Stage ──────────────────────────────────────────────────────────────


class ChatResponderNode(Node):
    def __init__(self) -> None:
        super().__init__(max_retries=2, wait=1)

    def prep(self, shared: dict[str, Any]) -> dict[str, Any]:
        return {
            "clean_message": shared.get("clean_message", ""),
            "intent": shared.get("intent", "chat"),
            "history_context": shared.get("history_context", ""),
            "api_key": shared["openrouter_api_key"],
            "model": shared["openrouter_model"],
        }

    def exec(self, prep_res: dict[str, Any]) -> str:
        system_prompt = _load_prompt("chat_responder_prompt.txt")
        clarify_instruction = ""
        if prep_res["intent"] == "clarify":
            clarify_instruction = (
                "\n\nThe user's question is ambiguous. Ask a targeted follow-up "
                "question to clarify what they want (e.g., career stats, recent games, "
                "comparisons, specific seasons)."
            )
        prompt = system_prompt.format(clarify_instruction=clarify_instruction)
        return call_llm(
            prompt=prep_res["clean_message"],
            api_key=prep_res["api_key"],
            model=prep_res["model"],
            system_prompt=prompt,
        )

    def exec_fallback(self, prep_res: Any, exc: Exception) -> str:
        return "I'm sorry, I couldn't process that request. Could you try again?"

    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: str) -> str:
        shared["response"] = exec_res
        chat_history: list = shared.setdefault("chat_history", [])
        chat_history.append({
            "role": "assistant",
            "content": exec_res,
            "sql": None,
            "error": False,
        })
        _log_step(shared, "ChatResponder", "chat response generated")
        return "default"
