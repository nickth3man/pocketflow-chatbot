"""Tests for schema/SQL nodes: TableSelector, QueryPlanner, SQLGenerator, SQLExecutor."""

from nodes import (
    QueryPlannerNode,
    SQLExecutorNode,
    SQLGeneratorNode,
    TableSelectorNode,
)


class TestTableSelectorNode:
    def test_prep_reads_shared(self, shared):
        shared["clean_message"] = "points per game"
        shared["entities"] = {
            "players": [],
            "teams": ["Warriors"],
            "seasons": ["2023-24"],
        }
        shared["history_context"] = ""
        node = TableSelectorNode()
        result = node.prep(shared)
        assert result["clean_message"] == "points per game"
        assert "dim_player" in result["table_listing"]
        assert "fact_player_game_stats" in result["table_listing"]

    def test_exec_calls_llm_structured(self, shared, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "tables": ["fact_player_game_stats", "dim_player"],
            "reason": "needed",
        }
        node = TableSelectorNode()
        prep_res = {
            "clean_message": "points",
            "entities": {},
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "table_listing": "- dim_player\n- fact_player_game_stats",
            "schema_by_table": shared["schema_by_table"],
            "system_prompt": "",
        }
        result = node.exec(prep_res)
        assert "fact_player_game_stats" in result["tables"]
        mock_call_llm_structured.assert_called_once()

    def test_post_writes_selected_tables_and_schema(self, shared):
        node = TableSelectorNode()
        exec_res = {
            "tables": ["dim_player", "fact_player_game_stats"],
            "reason": "stats",
        }
        prep_res = {"schema_by_table": shared["schema_by_table"]}
        node.post(shared, prep_res, exec_res)
        assert shared["selected_tables"] == ["dim_player", "fact_player_game_stats"]
        assert "TABLE dim_player" in shared["schema_context"]
        assert "TABLE fact_player_game_stats" in shared["schema_context"]


class TestQueryPlannerNode:
    def test_prep_reads_shared(self, shared):
        shared["clean_message"] = "avg points"
        shared["schema_context"] = "TABLE dim_player"
        node = QueryPlannerNode()
        result = node.prep(shared)
        assert result["clean_message"] == "avg points"
        assert result["schema_context"] == "TABLE dim_player"

    def test_exec_calls_llm_structured(self, shared, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "plan": "Join dim_player with fact_player_game_stats",
            "tables_used": ["dim_player", "fact_player_game_stats"],
            "filters": ["season = 2023-24"],
            "aggregations": ["AVG(points)"],
        }
        node = QueryPlannerNode()
        prep_res = {
            "clean_message": "avg points",
            "entities": {},
            "schema_context": "TABLE dim_player",
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "system_prompt": "",
        }
        result = node.exec(prep_res)
        assert "fact_player_game_stats" in result["plan"]
        mock_call_llm_structured.assert_called_once()

    def test_post_writes_plan(self, shared):
        node = QueryPlannerNode()
        node.post(
            shared,
            None,
            {
                "plan": "join and aggregate",
                "tables_used": [],
                "filters": [],
                "aggregations": [],
            },
        )
        assert shared["query_plan"] == "join and aggregate"


class TestSQLGeneratorNode:
    def test_prep_includes_error_context_when_present(self, shared):
        shared["execution_error"] = "column not found"
        shared["error_type"] = "missing_column"
        shared["error_analysis"] = {"root_cause": "wrong column name"}
        shared["schema_recheck"] = "TABLE dim_player (person_id BIGINT)"
        node = SQLGeneratorNode()
        result = node.prep(shared)
        assert result["execution_error"] == "column not found"
        assert result["error_type"] == "missing_column"

    def test_prep_error_context_is_none_on_first_pass(self, shared):
        shared["execution_error"] = None
        node = SQLGeneratorNode()
        result = node.prep(shared)
        assert result["execution_error"] is None

    def test_exec_calls_llm_structured(self, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "thinking": "simple select",
            "sql": "SELECT 1",
        }
        node = SQLGeneratorNode()
        prep_res = {
            "clean_message": "test",
            "schema_context": "TABLE dim_player",
            "query_plan": "get all",
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "system_prompt": "",
            "execution_error": None,
            "error_type": None,
            "error_analysis": None,
            "schema_recheck": None,
        }
        result = node.exec(prep_res)
        assert "SELECT 1" in result

    def test_exec_raises_on_non_select(self, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "thinking": "oops",
            "sql": "DROP TABLE dim_player",
        }
        node = SQLGeneratorNode()
        prep_res = {
            "clean_message": "test",
            "schema_context": "",
            "query_plan": "",
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "system_prompt": "",
            "execution_error": None,
            "error_type": None,
            "error_analysis": None,
            "schema_recheck": None,
        }
        import pytest

        with pytest.raises(ValueError, match="must start with SELECT"):
            node.exec(prep_res)

    def test_exec_includes_error_context_on_retry(self, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {"thinking": "fixed", "sql": "SELECT 1"}
        node = SQLGeneratorNode()
        prep_res = {
            "clean_message": "test",
            "schema_context": "",
            "query_plan": "",
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "system_prompt": "",
            "execution_error": "column not found",
            "error_type": "missing_column",
            "error_analysis": "wrong col",
            "schema_recheck": "check dim_player",
        }
        result = node.exec(prep_res)
        assert "SELECT 1" in result

    def test_exec_fallback_returns_safe_sql(self):
        node = SQLGeneratorNode()
        result = node.exec_fallback(None, ValueError("failed"))
        assert "SQL generation failed after retries" in result

    def test_post_optimizes_and_writes_sql(self, shared):
        node = SQLGeneratorNode()
        node.post(shared, None, "SELECT * FROM dim_player")
        assert shared["generated_sql"].strip().endswith("LIMIT 200;")
        assert shared["execution_error"] is None


class TestSQLExecutorNode:
    def test_prep_reads_shared(self, shared):
        shared["generated_sql"] = "SELECT 1"
        node = SQLExecutorNode()
        result = node.prep(shared)
        assert result["sql"] == "SELECT 1"
        assert result["db_path"] == ":memory:"
        assert result["max_rows"] == 200
        assert result["timeout"] == 30

    def test_exec_calls_execute_query(self, shared, mock_execute_query_success):
        node = SQLExecutorNode()
        prep_res = {
            "db_path": ":memory:",
            "sql": "SELECT 1",
            "max_rows": 200,
            "timeout": 30,
        }
        result = node.exec(prep_res)
        assert result["success"] is True
        mock_execute_query_success.assert_called_once_with(
            db_path=":memory:", sql="SELECT 1", max_rows=200, timeout_seconds=30
        )

    def test_post_success_branch(self, shared):
        node = SQLExecutorNode()
        exec_res = {
            "success": True,
            "columns": ["x"],
            "rows": [[1]],
            "elapsed_ms": 5.0,
            "error": None,
        }
        shared["generated_sql"] = "SELECT 1"
        result = node.post(shared, None, exec_res)
        assert shared["sql_result"] == exec_res
        assert shared["response_sql"] == "SELECT 1"
        assert result == "success"

    def test_post_error_branch(self, shared):
        node = SQLExecutorNode()
        exec_res = {
            "success": False,
            "columns": [],
            "rows": [],
            "elapsed_ms": 5.0,
            "error": "syntax error",
        }
        result = node.post(shared, None, exec_res)
        assert shared["execution_error"] == "syntax error"
        assert result == "error"
