"""Test entry points and edge cases across all modules."""

import os

import pytest


class TestEntryPoints:
    @pytest.mark.modify_env()
    def test_main_imports(self, mocker):
        mocker.patch("utils.get_full_schema.get_full_schema", return_value={})
        mocker.patch.dict(
            os.environ, {"OPENROUTER_API_KEY": "test", "OPENROUTER_MODEL": "test"}
        )
        import main

        assert main is not None

    @pytest.mark.modify_env()
    def test_build_shared_raises_on_missing_api_key(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
        )
        from app import build_shared

        with pytest.raises(SystemExit):
            build_shared()

    @pytest.mark.modify_env()
    def test_build_shared_raises_on_missing_model(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "",
                "DUCKDB_PATH": __file__,
            },
        )
        from app import build_shared

        with pytest.raises(SystemExit):
            build_shared()

    @pytest.mark.modify_env()
    def test_build_shared_raises_on_missing_db(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": "/nonexistent/path.duckdb",
            },
        )
        from app import build_shared

        with pytest.raises(SystemExit):
            build_shared()

    @pytest.mark.modify_env()
    def test_build_shared_succeeds_with_valid_input(self, mocker):
        import app as app_mod

        mocker.patch.object(app_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
        )
        result = app_mod.build_shared()
        assert result["openrouter_api_key"] == "test"
        assert result["openrouter_model"] == "test"
        assert "dummy" in result["schema_by_table"]

    @pytest.mark.modify_env()
    def test_main_build_shared_succeeds(self, mocker):
        import main as main_mod

        mocker.patch.object(main_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
        )
        result = main_mod.build_shared()
        assert result["openrouter_api_key"] == "test"
        assert result["openrouter_model"] == "test"


class TestGetShared:
    @pytest.mark.modify_env()
    @pytest.mark.enable_socket(allow_hosts=["127.0.0.1", "localhost"])
    def test_get_shared_initializes_once(self, mocker):
        import app as app_mod

        mocker.patch.object(app_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
        )
        s1 = app_mod.get_shared()
        s2 = app_mod.get_shared()
        assert s1 is s2

    @pytest.mark.modify_env()
    @pytest.mark.enable_socket(allow_hosts=["127.0.0.1", "localhost"])
    def test_reset_conversation_clears_shared(self, mocker):
        import app as app_mod

        mocker.patch.object(app_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
        )
        s1 = app_mod.get_shared()
        app_mod.reset_conversation()
        s2 = app_mod.get_shared()
        assert s1 is not s2


class TestSQLGeneratorSafetyCheck:
    def test_exec_raises_on_sql_with_embedded_ddl(self, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "thinking": "oops embedded drop",
            "sql": "SELECT * FROM t; DROP TABLE t",
        }
        from nodes import SQLGeneratorNode

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
        with pytest.raises(ValueError, match="SQL safety check failed"):
            node.exec(prep_res)


class TestExecuteQuery:
    def test_execute_query_timeout(self, mocker):
        from utils.execute_query import execute_query

        mocker.patch("utils.execute_query._run_query", side_effect=TimeoutError)
        result = execute_query(":memory:", "SELECT 1", max_rows=5, timeout_seconds=0)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_execute_query_success(self, mocker):
        from utils.execute_query import execute_query

        mocker.patch("utils.execute_query._run_query", return_value=(["x"], [[1]], 5.0))
        result = execute_query(":memory:", "SELECT 1", max_rows=5, timeout_seconds=30)
        assert result["success"] is True
        assert result["columns"] == ["x"]
        assert result["rows"] == [[1]]

    def test_execute_query_duckdb_error(self, mocker):
        from utils.execute_query import execute_query

        mocker.patch(
            "utils.execute_query._run_query", side_effect=RuntimeError("db error")
        )
        with pytest.raises(RuntimeError, match="db error"):
            execute_query(":memory:", "SELECT bad", max_rows=5, timeout_seconds=30)


class TestGetFullSchema:
    def test_get_full_schema_success(self, mocker):
        from utils.get_full_schema import get_full_schema

        mock_con = mocker.MagicMock()
        mock_con.execute.side_effect = [
            mocker.MagicMock(fetchall=lambda: [("dim_player", "BASE TABLE")]),
            mocker.MagicMock(fetchall=lambda: [("person_id", "BIGINT")]),
            mocker.MagicMock(fetchone=lambda: (100,)),
        ]
        mocker.patch("duckdb.connect", return_value=mock_con)
        result = get_full_schema("fake.db")
        assert "dim_player" in result
        assert result["dim_player"]["row_count"] == 100
        assert result["dim_player"]["columns"][0]["name"] == "person_id"


class TestNodesEdgeCases:
    def test_sql_executor_all_defaults(self, shared, mocker):
        from nodes import SQLExecutorNode

        mock_exec = mocker.patch("nodes.execute_query")
        mock_exec.return_value = {
            "success": True,
            "columns": ["x"],
            "rows": [[1]],
            "elapsed_ms": 1.0,
            "error": None,
        }
        node = SQLExecutorNode()
        shared["db_path"] = "test.db"
        shared["generated_sql"] = "SELECT 1"
        result = node.exec(node.prep(shared))
        assert result["success"] is True

    def test_intent_classifier_handles_empty_clean_message(
        self, mock_call_llm_structured, shared
    ):
        from nodes import IntentClassifierNode

        mock_call_llm_structured.return_value = {"intent": "chat", "reason": "empty"}
        node = IntentClassifierNode()
        shared["clean_message"] = ""
        node.run(shared)
        assert shared["intent"] == "chat"


class TestHistoryContextBuilderEdgeCases:
    def test_formats_history_with_truncated_content(self):
        from nodes import HistoryContextBuilderNode

        node = HistoryContextBuilderNode()
        long_msg = "x" * 500
        history = [
            {"role": "user", "content": long_msg, "sql": None},
            {
                "role": "assistant",
                "content": "response",
                "sql": "SELECT * FROM dim_player WHERE player_name = " + "x" * 200,
            },
        ]
        result = node.exec(history)
        assert len(result) > 0
        assert "[user:" in result
        assert "[assistant:" in result
