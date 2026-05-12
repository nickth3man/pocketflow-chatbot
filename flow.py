import logging
import time
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
    SQLValidatorNode,
    TableSelectorNode,
    _log_step,
)

_logger = logging.getLogger("nba_chatbot")

ERROR_RECOVERY_FLOW_LABEL = "ErrorRecoveryFlow"


class ErrorRecoveryFlow(Flow):
    def post(self, shared: dict[str, Any], prep_res: Any, exec_res: Any) -> str:
        action = str(shared.get("recovery_action", "give_up"))
        attempts = shared.get("debug_attempts", 0)
        max_attempts = shared.get("max_debug_attempts", 3)
        _log_step(
            shared,
            ERROR_RECOVERY_FLOW_LABEL,
            f"decision={action} ({attempts}/{max_attempts} attempts)",
            extra={
                "subflow": "error_recovery",
                "action": action,
                "attempts_used": attempts,
                "max_attempts": max_attempts,
            },
        )
        return action


def create_chat_flow() -> Flow:
    start = time.monotonic()
    _logger.info("[Flow] creating chat flow DAG...")

    # ── Pre-processing ──────────────────────────────────────────────────
    message_preprocessor = MessagePreprocessorNode()
    history_context_builder = HistoryContextBuilderNode()
    intent_classifier = IntentClassifierNode()

    (message_preprocessor >> history_context_builder >> intent_classifier)
    _logger.debug(
        "[Flow] pre-processing chain: MessagePreprocessor → HistoryContextBuilder → IntentClassifier"
    )

    # ── Schema / Planning ───────────────────────────────────────────────
    table_selector = TableSelectorNode()
    query_planner = QueryPlannerNode()
    sql_generator = SQLGeneratorNode()

    (intent_classifier - "query_db" >> table_selector)
    _logger.debug("[Flow] query_db path: IntentClassifier → TableSelector")
    (table_selector >> query_planner >> sql_generator)
    _logger.debug("[Flow] planning chain: TableSelector → QueryPlanner → SQLGenerator")

    # ── Execution ───────────────────────────────────────────────────────
    sql_executor = SQLExecutorNode()

    # ── Response nodes (defined early so error flow can reference them) ─
    result_analyzer = ResultAnalyzerNode()
    response_builder = ResponseBuilderNode()

    (sql_executor - "success" >> result_analyzer)
    result_analyzer >> response_builder
    _logger.debug("[Flow] success path: SQLExecutor → ResultAnalyzer → ResponseBuilder")

    # ── Error Recovery (nested sub-Flow) ────────────────────────────────
    error_analyzer = ErrorAnalyzerNode()
    schema_recheck = SchemaRecheckNode()
    sql_fixer = SQLFixerNode()
    fix_validator = FixValidatorNode()
    recovery_decision = RecoveryDecisionNode()

    (
        error_analyzer
        >> schema_recheck
        >> sql_fixer
        >> fix_validator
        >> recovery_decision
    )

    error_recovery_flow = ErrorRecoveryFlow(start=error_analyzer)
    _logger.debug(
        "[Flow] error recovery chain: ErrorAnalyzer → SchemaRecheck → SQLFixer → FixValidator → RecoveryDecision"
    )

    sql_validator = SQLValidatorNode()
    sql_generator >> sql_validator >> sql_executor
    sql_generator - "generation_failed" >> response_builder
    sql_validator - "error" >> error_recovery_flow
    _logger.debug("[Flow] execution: SQLGenerator → SQLValidator → SQLExecutor")

    (sql_executor - "error" >> error_recovery_flow)
    _logger.debug("[Flow] error path: SQLExecutor → ErrorRecoveryFlow")
    (error_recovery_flow - "retry" >> sql_executor)
    _logger.debug(
        "[Flow] retry path: ErrorRecoveryFlow → SQLExecutor (re-execute fixed SQL)"
    )
    (error_recovery_flow - "give_up" >> result_analyzer)
    _logger.debug("[Flow] give_up path: ErrorRecoveryFlow → ResultAnalyzer")

    # ── Chat path ───────────────────────────────────────────────────────
    chat_responder = ChatResponderNode()

    (intent_classifier - "chat" >> chat_responder)
    (intent_classifier - "clarify" >> chat_responder)
    _logger.debug("[Flow] chat/clarify path: IntentClassifier → ChatResponder")

    flow = Flow(start=message_preprocessor)
    elapsed = (time.monotonic() - start) * 1000
    _logger.info(
        "[Flow] DAG created in %.0fms with %d nodes across 3 paths (query_db, chat, clarify)",
        elapsed,
        15,
        extra={"flow_creation_ms": round(elapsed, 1)},
    )

    return flow


chat_flow: Flow = create_chat_flow()
