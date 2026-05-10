"""Snapshot tests for output structures and formatting.

Regenerate snapshots with: pytest --snapshot-update
"""

from nodes import (
    ErrorAnalyzerNode,
    IntentClassifierNode,
    MessagePreprocessorNode,
    QueryPlannerNode,
    SQLFixerNode,
    SQLGeneratorNode,
    TableSelectorNode,
)
from utils.classify_error import classify_error
from utils.format_response_markdown import format_response_markdown
from utils.format_results_table import format_results_table
from utils.format_schema import format_schema
from utils.optimize_sql import optimize_sql
from utils.validate_sql_safety import validate_sql_safety


class TestFormatSnapshots:
    def test_format_response_markdown_full(self, snapshot):
        result = format_response_markdown(
            narrative="Found 12 players.",
            table_md="| Name |\n| --- |\n| Curry |",
            sql="SELECT * FROM dim_player",
            elapsed_ms=42.5,
        )
        assert result == snapshot

    def test_format_response_markdown_no_sql(self, snapshot):
        result = format_response_markdown(
            narrative="Hello.", table_md="", sql=None, elapsed_ms=None
        )
        assert result == snapshot

    def test_format_results_table_basic(self, snapshot):
        result = format_results_table(
            ["Name", "Points"], [["Curry", 30], ["LeBron", 25]]
        )
        assert result == snapshot

    def test_format_results_table_truncation(self, snapshot):
        rows = [[str(i)] for i in range(60)]
        result = format_results_table(["X"], rows, max_display=50)
        assert result == snapshot

    def test_format_results_table_with_none(self, snapshot):
        result = format_results_table(["A", "B"], [[None, "x"], ["y", None]])
        assert result == snapshot

    def test_format_results_table_empty(self, snapshot):
        result = format_results_table([], [])
        assert result == snapshot

    def test_format_schema_basic(self, snapshot):
        schema = {"dim_player": {"columns": [{"name": "person_id", "type": "BIGINT"}]}}
        result = format_schema(schema)
        assert result == snapshot


class TestUtilitySnapshots:
    def test_validate_sql_safety_select(self, snapshot):
        result = validate_sql_safety("SELECT * FROM dim_player")
        assert result == snapshot

    def test_validate_sql_safety_drop(self, snapshot):
        result = validate_sql_safety("DROP TABLE dim_player")
        assert result == snapshot

    def test_validate_sql_safety_insert(self, snapshot):
        result = validate_sql_safety("INSERT INTO dim_player VALUES (1)")
        assert result == snapshot

    def test_validate_sql_safety_empty(self, snapshot):
        result = validate_sql_safety("")
        assert result == snapshot

    def test_classify_error_syntax(self, snapshot):
        result = classify_error("syntax error at or near")
        assert result == snapshot

    def test_classify_error_missing_column(self, snapshot):
        result = classify_error('column "foobar" does not exist')
        assert result == snapshot

    def test_classify_error_missing_table(self, snapshot):
        result = classify_error('table "foobar" does not exist')
        assert result == snapshot

    def test_classify_error_unknown(self, snapshot):
        result = classify_error("random internal error")
        assert result == snapshot

    def test_optimize_sql_adds_limit(self, snapshot):
        result = optimize_sql("SELECT * FROM dim_player")
        assert result == snapshot

    def test_optimize_sql_preserves_limit(self, snapshot):
        result = optimize_sql("SELECT * FROM dim_player LIMIT 5")
        assert result == snapshot


class TestNodeSchemaSnapshots:
    def test_message_preprocessor_exec_output(
        self, shared, mock_call_llm_structured, snapshot
    ):
        mock_call_llm_structured.return_value = {
            "clean_message": "Who scored the most points?",
            "entities": {"players": [], "teams": ["Lakers"], "seasons": ["2023-24"]},
        }
        node = MessagePreprocessorNode()
        prep_res = node.prep(shared)
        result = node.exec(prep_res)
        assert result == snapshot

    def test_intent_classifier_exec_output(
        self, shared, mock_call_llm_structured, snapshot
    ):
        mock_call_llm_structured.return_value = {
            "intent": "query_db",
            "reason": "user is asking for player statistics",
        }
        node = IntentClassifierNode()
        prep_res = node.prep(shared)
        result = node.exec(prep_res)
        assert result == snapshot

    def test_table_selector_exec_output(
        self, shared, mock_call_llm_structured, snapshot
    ):
        mock_call_llm_structured.return_value = {
            "tables": ["dim_player", "fact_player_game_stats"],
            "reason": "needed for player points query",
        }
        node = TableSelectorNode()
        prep_res = node.prep(shared)
        result = node.exec(prep_res)
        assert result == snapshot

    def test_query_planner_exec_output(
        self, shared, mock_call_llm_structured, snapshot
    ):
        mock_call_llm_structured.return_value = {
            "plan": "Join dim_player with fact_player_game_stats on person_id, group by player, average points",
            "tables_used": ["dim_player", "fact_player_game_stats"],
            "filters": ["season = 2023-24"],
            "aggregations": ["AVG(points)"],
        }
        shared["clean_message"] = "average points per game"
        shared["schema_context"] = (
            "TABLE dim_player (person_id BIGINT, first_name VARCHAR)"
        )
        node = QueryPlannerNode()
        prep_res = node.prep(shared)
        result = node.exec(prep_res)
        assert result == snapshot

    def test_sql_generator_exec_output(self, mock_call_llm_structured, snapshot):
        mock_call_llm_structured.return_value = {
            "thinking": "Simple select to get all players",
            "sql": "SELECT person_id, first_name, last_name FROM dim_player",
        }
        node = SQLGeneratorNode()
        prep_res = {
            "clean_message": "list players",
            "schema_context": "TABLE dim_player (person_id BIGINT, first_name VARCHAR, last_name VARCHAR)",
            "query_plan": "select all players",
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
        assert result == snapshot

    def test_error_analyzer_exec_output(
        self, shared, mock_call_llm_structured, snapshot
    ):
        mock_call_llm_structured.return_value = {
            "error_type": "missing_column",
            "root_cause": "Referenced column 'foobar' does not exist in dim_player",
            "affected_entities": ["dim_player"],
            "suggested_fix_direction": "Check the schema of dim_player and use a valid column name like person_id",
        }
        node = ErrorAnalyzerNode()
        shared["clean_message"] = "show me foobar"
        shared["generated_sql"] = "SELECT foobar FROM dim_player"
        shared["execution_error"] = 'column "foobar" does not exist'
        shared["schema_context"] = (
            "TABLE dim_player (person_id BIGINT, first_name VARCHAR)"
        )
        prep_res = node.prep(shared)
        result = node.exec(prep_res)
        assert result == snapshot

    def test_sql_fixer_exec_output(self, mock_call_llm_structured, snapshot):
        mock_call_llm_structured.return_value = {
            "thinking": "Fixed by using valid column name",
            "sql": "SELECT person_id FROM dim_player",
        }
        node = SQLFixerNode()
        prep_res = {
            "clean_message": "show players",
            "generated_sql": "SELECT foobar FROM dim_player",
            "error_type": "missing_column",
            "error_analysis": {"root_cause": "bad column"},
            "schema_recheck": "TABLE dim_player (person_id BIGINT)",
            "query_plan": "select all",
            "api_key": "k",
            "model": "m",
        }
        result = node.exec(prep_res)
        assert result == snapshot
