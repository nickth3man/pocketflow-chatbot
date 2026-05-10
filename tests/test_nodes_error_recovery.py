"""Tests for error recovery nodes: ErrorAnalyzer, SchemaRecheck, SQLFixer, FixValidator, RecoveryDecision."""

from nodes import (
    ErrorAnalyzerNode,
    FixValidatorNode,
    RecoveryDecisionNode,
    SchemaRecheckNode,
    SQLFixerNode,
)


class TestErrorAnalyzerNode:
    def test_prep_calls_classify_error(self, shared):
        shared["execution_error"] = 'column "foobar" does not exist'
        shared["generated_sql"] = "SELECT * FROM fake"
        shared["clean_message"] = "test"
        shared["schema_context"] = "TABLE dim_player"
        node = ErrorAnalyzerNode()
        result = node.prep(shared)
        assert result["error_type"] == "missing_column"

    def test_exec_calls_llm_structured(self, shared, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "error_type": "missing_column",
            "root_cause": "wrong column name",
            "affected_entities": ["dim_player"],
            "suggested_fix_direction": "check column names",
        }
        node = ErrorAnalyzerNode()
        prep_res = {
            "execution_error": "error",
            "error_type": "missing_column",
            "generated_sql": "SELECT *",
            "clean_message": "test",
            "schema_context": "",
            "api_key": "k",
            "model": "m",
        }
        result = node.exec(prep_res)
        assert result["root_cause"] == "wrong column name"
        mock_call_llm_structured.assert_called_once()

    def test_post_writes_error_type_and_analysis(self, shared):
        node = ErrorAnalyzerNode()
        exec_res = {
            "error_type": "missing_column",
            "root_cause": "bad col",
            "affected_entities": [],
            "suggested_fix_direction": "",
        }
        prep_res = {"error_type": "missing_column"}
        node.post(shared, prep_res, exec_res)
        assert shared["error_type"] == "missing_column"
        assert shared["error_analysis"] == exec_res


class TestSchemaRecheckNode:
    def test_prep_extracts_affected_from_error_analysis(self, shared):
        shared["error_analysis"] = {"affected_entities": ["dim_player"]}
        node = SchemaRecheckNode()
        result = node.prep(shared)
        assert "dim_player" in result["affected_entities"]

    def test_exec_returns_formatted_subset(self, shared):
        node = SchemaRecheckNode()
        prep_res = {
            "affected_entities": ["dim_player"],
            "schema_by_table": shared["schema_by_table"],
        }
        result = node.exec(prep_res)
        assert "TABLE dim_player" in result
        assert "person_id" in result

    def test_exec_empty_affected_returns_empty(self):
        node = SchemaRecheckNode()
        result = node.exec({"affected_entities": [], "schema_by_table": {}})
        assert result == ""

    def test_post_writes_schema_recheck(self, shared):
        node = SchemaRecheckNode()
        node.post(shared, None, "TABLE dim_player")
        assert shared["schema_recheck"] == "TABLE dim_player"


class TestSQLFixerNode:
    def test_prep_reads_all_error_context(self, shared):
        shared["clean_message"] = "test"
        shared["generated_sql"] = "SELECT bad"
        shared["error_type"] = "missing_column"
        shared["error_analysis"] = {"root_cause": "bad col"}
        shared["schema_recheck"] = "TABLE dim_player (person_id BIGINT)"
        shared["query_plan"] = "join tables"
        node = SQLFixerNode()
        result = node.prep(shared)
        assert result["clean_message"] == "test"
        assert result["error_type"] == "missing_column"

    def test_exec_returns_fixed_sql(self, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "thinking": "fixed column",
            "sql": "SELECT person_id FROM dim_player",
        }
        node = SQLFixerNode()
        prep_res = {
            "clean_message": "t",
            "generated_sql": "SELECT bad",
            "error_type": "mc",
            "error_analysis": {},
            "schema_recheck": "TABLE",
            "query_plan": "join",
            "api_key": "k",
            "model": "m",
        }
        result = node.exec(prep_res)
        assert "SELECT person_id" in result

    def test_exec_raises_on_non_select(self, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "thinking": "oops",
            "sql": "DELETE FROM dim_player",
        }
        node = SQLFixerNode()
        import pytest

        prep_res = {
            "clean_message": "t",
            "generated_sql": "SELECT bad",
            "error_type": "mc",
            "error_analysis": {},
            "schema_recheck": "TABLE",
            "query_plan": "join",
            "api_key": "k",
            "model": "m",
        }
        with pytest.raises(ValueError, match="Fixed SQL must start with SELECT"):
            node.exec(prep_res)

    def test_post_writes_fixed_sql(self, shared):
        node = SQLFixerNode()
        node.post(shared, None, "SELECT person_id FROM dim_player")
        assert shared["fixed_sql"] == "SELECT person_id FROM dim_player"


class TestFixValidatorNode:
    def test_exec_validates_safe_sql(self):
        node = FixValidatorNode()
        is_safe, _reason = node.exec("SELECT * FROM dim_player")
        assert is_safe is True

    def test_exec_validates_unsafe_sql(self):
        node = FixValidatorNode()
        is_safe, _reason = node.exec("DROP TABLE dim_player")
        assert is_safe is False

    def test_post_overwrites_generated_sql_when_safe(self, shared):
        shared["fixed_sql"] = "SELECT 1"
        shared["generated_sql"] = "SELECT old"
        node = FixValidatorNode()
        node.post(shared, None, (True, "safe"))
        assert shared["generated_sql"] == "SELECT 1"

    def test_post_does_not_overwrite_when_unsafe(self, shared):
        shared["fixed_sql"] = "DROP TABLE dim_player"
        shared["generated_sql"] = "SELECT old"
        node = FixValidatorNode()
        node.post(shared, None, (False, "unsafe"))
        assert shared["generated_sql"] == "SELECT old"


class TestRecoveryDecisionNode:
    def test_prep_increments_attempts(self, shared):
        shared["debug_attempts"] = 1
        node = RecoveryDecisionNode()
        result = node.prep(shared)
        assert result["debug_attempts"] == 2
        assert shared["debug_attempts"] == 2

    def test_exec_returns_retry_when_below_max(self):
        node = RecoveryDecisionNode()
        result = node.exec({
            "debug_attempts": 1,
            "max_debug_attempts": 3,
            "error_type": "syntax_error",
        })
        assert result == "retry"

    def test_exec_returns_retry_on_second_attempt(self):
        node = RecoveryDecisionNode()
        result = node.exec({
            "debug_attempts": 2,
            "max_debug_attempts": 3,
            "error_type": "syntax_error",
        })
        assert result == "retry"

    def test_exec_returns_give_up_when_at_max(self):
        node = RecoveryDecisionNode()
        result = node.exec({
            "debug_attempts": 3,
            "max_debug_attempts": 3,
            "error_type": "syntax_error",
        })
        assert result == "give_up"

    def test_exec_returns_give_up_on_permission_error(self):
        node = RecoveryDecisionNode()
        result = node.exec({
            "debug_attempts": 1,
            "max_debug_attempts": 3,
            "error_type": "permission",
        })
        assert result == "give_up"

    def test_post_writes_recovery_action(self, shared):
        node = RecoveryDecisionNode()
        node.post(shared, None, "retry")
        assert shared["recovery_action"] == "retry"
