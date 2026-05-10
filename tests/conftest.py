from typing import Any

import pytest
from pytest_check import check as check


@pytest.fixture
def shared() -> dict[str, Any]:
    return {
        "db_path": ":memory:",
        "schema_by_table": {
            "dim_player": {
                "columns": [
                    {"name": "person_id", "type": "BIGINT"},
                    {"name": "first_name", "type": "VARCHAR"},
                    {"name": "last_name", "type": "VARCHAR"},
                ],
                "row_count": 100,
            },
            "dim_team": {
                "columns": [
                    {"name": "team_id", "type": "BIGINT"},
                    {"name": "team_name", "type": "VARCHAR"},
                    {"name": "team_abbrev", "type": "VARCHAR"},
                ],
                "row_count": 30,
            },
            "fact_game": {
                "columns": [
                    {"name": "game_id", "type": "VARCHAR"},
                    {"name": "game_date", "type": "DATE"},
                    {"name": "home_score", "type": "INTEGER"},
                    {"name": "away_score", "type": "INTEGER"},
                ],
                "row_count": 10000,
            },
            "fact_player_game_stats": {
                "columns": [
                    {"name": "game_id", "type": "VARCHAR"},
                    {"name": "person_id", "type": "BIGINT"},
                    {"name": "points", "type": "INTEGER"},
                    {"name": "assists", "type": "INTEGER"},
                ],
                "row_count": 50000,
            },
            "fact_team_game_stats": {
                "columns": [
                    {"name": "game_id", "type": "VARCHAR"},
                    {"name": "team_id", "type": "BIGINT"},
                    {"name": "pts", "type": "INTEGER"},
                    {"name": "net_rating", "type": "DOUBLE"},
                ],
                "row_count": 20000,
            },
            "fact_play_by_play": {
                "columns": [
                    {"name": "game_id", "type": "VARCHAR"},
                    {"name": "player_name", "type": "VARCHAR"},
                    {"name": "action_type", "type": "VARCHAR"},
                    {"name": "period", "type": "SMALLINT"},
                ],
                "row_count": 100000,
            },
            "fact_game_main_line": {
                "columns": [
                    {"name": "team1_name", "type": "VARCHAR"},
                    {"name": "team2_name", "type": "VARCHAR"},
                    {"name": "team1_moneyline", "type": "DOUBLE"},
                    {"name": "team2_moneyline", "type": "DOUBLE"},
                ],
                "row_count": 1000,
            },
        },
        "openrouter_api_key": "test-api-key",
        "openrouter_model": "test-model",
        "db_query_timeout": 30,
        "max_rows": 200,
        "chat_history": [],
        "user_message": "",
        "clean_message": "",
        "entities": {"players": [], "teams": [], "seasons": []},
        "history_context": "",
        "intent": "",
        "selected_tables": [],
        "schema_context": "",
        "query_plan": "",
        "generated_sql": "",
        "sql_result": None,
        "execution_error": None,
        "debug_attempts": 0,
        "max_debug_attempts": 3,
        "error_type": "",
        "error_analysis": {},
        "schema_recheck": "",
        "fixed_sql": "",
        "recovery_action": "",
        "result_analysis": "",
        "response": "",
        "response_sql": "",
        "step_logs": [],
    }


@pytest.fixture
def mock_call_llm(mocker):
    return mocker.patch("nodes.call_llm", return_value="Mocked LLM response")


@pytest.fixture
def mock_call_llm_structured(mocker):
    fixture = mocker.patch("nodes.call_llm_structured")
    fixture.return_value = {
        "clean_message": "test query",
        "entities": {"players": [], "teams": [], "seasons": []},
    }
    return fixture


@pytest.fixture
def mock_execute_query_success(mocker):
    fixture = mocker.patch("nodes.execute_query")
    fixture.return_value = {
        "success": True,
        "columns": ["player_name", "points"],
        "rows": [["Curry", 30], ["LeBron", 25]],
        "elapsed_ms": 15.0,
        "error": None,
    }
    return fixture


@pytest.fixture
def mock_execute_query_failure(mocker):
    fixture = mocker.patch("nodes.execute_query")
    fixture.return_value = {
        "success": False,
        "columns": [],
        "rows": [],
        "elapsed_ms": 10.0,
        "error": 'Binder Error: column "foobar" does not exist',
    }
    return fixture
