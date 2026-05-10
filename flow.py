import logging
from typing import Any

from pocketflow import Flow

from nodes import (
    ChatResponderNode,
    ErrorAnalyzerNode,
    FixValidatorNode,
    HistoryContextBuilderNode,
    IntentClassifierNode,
    MessagePreprocessorNode,
    QueryPlannerNode,
    RecoveryDecisionNode,
    ResponseBuilderNode,
    ResultAnalyzerNode,
    SchemaRecheckNode,
    SQLExecutorNode,
    SQLFixerNode,
    SQLGeneratorNode,
    TableSelectorNode,
)

_logger = logging.getLogger("nba_chatbot")


class ErrorRecoveryFlow(Flow):
    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        action = str(shared.get("recovery_action", "give_up"))
        _logger.info("[ErrorRecoveryFlow] post: action=%s", action)
        shared.setdefault("step_logs", []).append({
            "node": "ErrorRecoveryFlow",
            "status": "complete",
            "summary": f"sub-flow action={action}",
        })
        return action


def create_chat_flow() -> Flow:
    # ── Pre-processing ──────────────────────────────────────────────────
    message_preprocessor = MessagePreprocessorNode()
    history_context_builder = HistoryContextBuilderNode()
    intent_classifier = IntentClassifierNode()

    (
        message_preprocessor
        >> history_context_builder  # pyright: ignore[reportUnusedExpression]
        >> intent_classifier  # pyright: ignore[reportUnusedExpression]
    )

    # ── Schema / Planning ───────────────────────────────────────────────
    table_selector = TableSelectorNode()
    query_planner = QueryPlannerNode()
    sql_generator = SQLGeneratorNode()

    (
        intent_classifier - "query_db"  # pyright: ignore[reportUnusedExpression]
        >> table_selector  # pyright: ignore[reportUnusedExpression]
    )
    (
        table_selector
        >> query_planner  # pyright: ignore[reportUnusedExpression]
        >> sql_generator  # pyright: ignore[reportUnusedExpression]
    )

    # ── Execution ───────────────────────────────────────────────────────
    sql_executor = SQLExecutorNode()
    sql_generator >> sql_executor  # pyright: ignore[reportUnusedExpression]

    # ── Response nodes (defined early so error flow can reference them) ─
    result_analyzer = ResultAnalyzerNode()
    response_builder = ResponseBuilderNode()

    (
        sql_executor - "success"  # pyright: ignore[reportUnusedExpression]
        >> result_analyzer  # pyright: ignore[reportUnusedExpression]
    )
    result_analyzer >> response_builder  # pyright: ignore[reportUnusedExpression]

    # ── Error Recovery (nested sub-Flow) ────────────────────────────────
    error_analyzer = ErrorAnalyzerNode()
    schema_recheck = SchemaRecheckNode()
    sql_fixer = SQLFixerNode()
    fix_validator = FixValidatorNode()
    recovery_decision = RecoveryDecisionNode()

    (
        error_analyzer
        >> schema_recheck  # pyright: ignore[reportUnusedExpression]
        >> sql_fixer  # pyright: ignore[reportUnusedExpression]
        >> fix_validator  # pyright: ignore[reportUnusedExpression]
        >> recovery_decision  # pyright: ignore[reportUnusedExpression]
    )

    error_recovery_flow = ErrorRecoveryFlow(start=error_analyzer)

    (
        sql_executor - "error"  # pyright: ignore[reportUnusedExpression]
        >> error_recovery_flow  # pyright: ignore[reportUnusedExpression]
    )
    (
        error_recovery_flow - "retry"  # pyright: ignore[reportUnusedExpression]
        >> sql_generator  # pyright: ignore[reportUnusedExpression]
    )
    (
        error_recovery_flow - "give_up"  # pyright: ignore[reportUnusedExpression]
        >> result_analyzer  # pyright: ignore[reportUnusedExpression]
    )

    # ── Chat path ───────────────────────────────────────────────────────
    chat_responder = ChatResponderNode()

    (
        intent_classifier - "chat"  # pyright: ignore[reportUnusedExpression]
        >> chat_responder  # pyright: ignore[reportUnusedExpression]
    )
    (
        intent_classifier - "clarify"  # pyright: ignore[reportUnusedExpression]
        >> chat_responder  # pyright: ignore[reportUnusedExpression]
    )

    return Flow(start=message_preprocessor)


chat_flow: Flow = create_chat_flow()
