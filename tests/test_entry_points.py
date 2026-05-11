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


class TestAppFormatStepTrace:
    @pytest.mark.modify_env()
    def test_format_step_trace_empty(self, mocker):
        mocker.patch("app.load_dotenv")
        from app import _format_step_trace_html

        result = _format_step_trace_html([])
        assert "empty-state" in result

    @pytest.mark.modify_env()
    def test_format_step_trace_with_steps(self, mocker):
        mocker.patch("app.load_dotenv")
        from app import _format_step_trace_html

        logs = [
            {"node": "Preprocess", "status": "complete", "summary": "cleaned message"},
            {"node": "SQLExecutor", "status": "error", "summary": "query failed"},
        ]
        result = _format_step_trace_html(logs)
        assert "Preprocess" in result
        assert "SQLExecutor" in result
        assert "step-done" in result
        assert "step-err" in result
        assert "cleaned message" in result
        assert "query failed" in result

    @pytest.mark.modify_env()
    def test_format_step_trace_single_step(self, mocker):
        mocker.patch("app.load_dotenv")
        from app import _format_step_trace_html

        logs = [{"node": "Test", "status": "complete", "summary": "done"}]
        result = _format_step_trace_html(logs)
        assert "Test" in result
        assert "done" in result


class TestAppOnClear:
    @pytest.mark.modify_env()
    @pytest.mark.enable_socket(allow_hosts=["127.0.0.1", "localhost"])
    def test_on_clear_returns_empty_and_resets(self, mocker):
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
        from app import _on_clear

        # Ensure shared is initialized
        app_mod.get_shared()
        result = _on_clear()
        msg_out, step_out, _meta_out, chart_out = result
        assert msg_out == ""
        assert step_out == ""
        assert chart_out is None


class TestQueryPlannerPlanAsList:
    def test_post_converts_list_plan_to_string(self, shared):
        from nodes import QueryPlannerNode

        node = QueryPlannerNode()
        exec_res = {
            "plan": ["Step 1: join", "Step 2: filter", "Step 3: aggregate"],
            "tables_used": [],
            "filters": [],
            "aggregations": [],
        }
        node.post(shared, None, exec_res)
        assert isinstance(shared["query_plan"], str)
        assert shared["query_plan"] == "Step 1: join, Step 2: filter, Step 3: aggregate"


class TestMainBuildSharedPaths:
    @pytest.mark.modify_env()
    def test_main_build_shared_missing_api_key(self, mocker):
        mocker.patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "", "OPENROUTER_MODEL": "test"},
            clear=True,
        )
        import main as main_mod

        with pytest.raises(SystemExit):
            main_mod.build_shared()

    @pytest.mark.modify_env()
    def test_main_build_shared_missing_model(self, mocker):
        mocker.patch.dict(
            os.environ,
            {"OPENROUTER_API_KEY": "test", "OPENROUTER_MODEL": ""},
            clear=True,
        )
        import main as main_mod

        with pytest.raises(SystemExit):
            main_mod.build_shared()

    @pytest.mark.modify_env()
    def test_main_build_shared_missing_db(self, mocker):
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": "/nonexistent/path.duckdb",
            },
            clear=True,
        )
        import main as main_mod

        with pytest.raises(SystemExit):
            main_mod.build_shared()

    @pytest.mark.modify_env()
    def test_main_function_one_iteration(self, mocker):
        import main as main_mod

        mocker.patch.object(main_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.object(main_mod.chat_flow, "run")
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
            clear=True,
        )
        mocker.patch("builtins.input", side_effect=["hello", "quit"])
        mocker.patch("builtins.print")

        main_mod.main()

    @pytest.mark.modify_env()
    def test_main_empty_input_skips(self, mocker):
        import main as main_mod

        mocker.patch.object(main_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.object(main_mod.chat_flow, "run")
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
            clear=True,
        )
        mocker.patch("builtins.input", side_effect=["", "quit"])
        mocker.patch("builtins.print")

        main_mod.main()

    @pytest.mark.modify_env()
    def test_main_eof_error_breaks(self, mocker):
        import main as main_mod

        mocker.patch.object(main_mod, "get_full_schema", return_value={"dummy": {}})
        mocker.patch.object(main_mod.chat_flow, "run")
        mocker.patch.dict(
            os.environ,
            {
                "OPENROUTER_API_KEY": "test",
                "OPENROUTER_MODEL": "test",
                "DUCKDB_PATH": __file__,
            },
            clear=True,
        )
        mocker.patch("builtins.input", side_effect=EOFError)
        mocker.patch("builtins.print")

        main_mod.main()


class TestLoggingSetup:
    def test_get_logger_returns_nba_chatbot_logger(self):
        from utils.logging_setup import get_logger

        logger = get_logger()
        assert logger.name == "nba_chatbot"

    def test_setup_logging_returns_logger(self):
        from utils.logging_setup import setup_logging

        logger = setup_logging()
        assert logger.name == "nba_chatbot"
        assert logger.level <= 10  # DEBUG level

    def test_setup_logging_is_idempotent(self):
        from utils.logging_setup import setup_logging

        logger1 = setup_logging()
        logger2 = setup_logging()
        assert logger1 is logger2
