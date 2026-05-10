"""Tests for response nodes: ResultAnalyzer, ResponseBuilder, ChatResponder."""

from nodes import ChatResponderNode, ResponseBuilderNode, ResultAnalyzerNode


class TestResultAnalyzerNode:
    def test_prep_detects_has_results_true(self, shared):
        shared["sql_result"] = {
            "success": True,
            "columns": ["x"],
            "rows": [[1]],
            "elapsed_ms": 5.0,
        }
        node = ResultAnalyzerNode()
        result = node.prep(shared)
        assert result["has_results"]

    def test_prep_detects_has_results_false(self, shared):
        shared["sql_result"] = None
        node = ResultAnalyzerNode()
        result = node.prep(shared)
        assert not result["has_results"]

    def test_prep_detects_has_results_empty_rows(self, shared):
        shared["sql_result"] = {
            "success": True,
            "columns": ["x"],
            "rows": [],
            "elapsed_ms": 5.0,
        }
        node = ResultAnalyzerNode()
        result = node.prep(shared)
        assert not result["has_results"]

    def test_exec_with_results_calls_llm(self, shared, mock_call_llm):
        node = ResultAnalyzerNode()
        prep_res = {
            "clean_message": "top scorers",
            "sql_result": {
                "columns": ["name", "pts"],
                "rows": [["Curry", 30]],
                "elapsed_ms": 5.0,
            },
            "has_results": True,
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "debug_attempts": 1,
            "max_debug_attempts": 3,
        }
        result = node.exec(prep_res)
        assert isinstance(result, str)
        mock_call_llm.assert_called_once()

    def test_exec_without_results_calls_llm(self, shared, mock_call_llm):
        node = ResultAnalyzerNode()
        prep_res = {
            "clean_message": "top scorers",
            "sql_result": None,
            "has_results": False,
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "debug_attempts": 3,
            "max_debug_attempts": 3,
        }
        result = node.exec(prep_res)
        assert isinstance(result, str)
        assert mock_call_llm.called

    def test_exec_fallback_returns_graceful_message(self):
        node = ResultAnalyzerNode()
        result = node.exec_fallback(None, Exception("fail"))
        assert "rephrasing" in result

    def test_post_writes_analysis(self, shared):
        node = ResultAnalyzerNode()
        node.post(shared, None, "analysis text")
        assert shared["result_analysis"] == "analysis text"


class TestResponseBuilderNode:
    def test_prep_reads_all_fields(self, shared):
        shared["result_analysis"] = "analysis"
        shared["sql_result"] = {
            "success": True,
            "columns": ["x"],
            "rows": [[1]],
            "elapsed_ms": 5.0,
        }
        shared["response_sql"] = "SELECT 1"
        node = ResponseBuilderNode()
        result = node.prep(shared)
        assert result["result_analysis"] == "analysis"
        assert result["response_sql"] == "SELECT 1"

    def test_exec_with_results_builds_full_markdown(self, shared):
        node = ResponseBuilderNode()
        prep_res = {
            "result_analysis": "Found 2 players.",
            "sql_result": {
                "success": True,
                "columns": ["Name"],
                "rows": [["Curry"], ["LeBron"]],
                "elapsed_ms": 5.0,
            },
            "response_sql": "SELECT * FROM players",
            "debug_attempts": 0,
            "max_debug_attempts": 3,
        }
        result = node.exec(prep_res)
        assert "Found 2 players." in result
        assert "| Name |" in result
        assert "SELECT * FROM players" in result

    def test_exec_without_result_sql_still_builds(self, shared):
        node = ResponseBuilderNode()
        prep_res = {
            "result_analysis": "Could not query.",
            "sql_result": None,
            "response_sql": None,
            "debug_attempts": 3,
            "max_debug_attempts": 3,
        }
        result = node.exec(prep_res)
        assert "Could not query." in result
        assert "View SQL" not in result

    def test_post_appends_to_chat_history(self, shared):
        node = ResponseBuilderNode()
        prep_res = {
            "result_analysis": "analysis",
            "sql_result": None,
            "response_sql": None,
            "debug_attempts": 0,
            "max_debug_attempts": 3,
        }
        shared["response"] = ""
        node.post(shared, prep_res, "response text")
        assert shared["response"] == "response text"
        assert len(shared["chat_history"]) == 1
        assert shared["chat_history"][0]["role"] == "assistant"


class TestChatResponderNode:
    def test_prep_reads_shared(self, shared):
        shared["clean_message"] = "hello"
        shared["intent"] = "chat"
        node = ChatResponderNode()
        result = node.prep(shared)
        assert result["clean_message"] == "hello"
        assert result["intent"] == "chat"

    def test_exec_calls_llm_for_chat(self, shared, mock_call_llm):
        node = ChatResponderNode()
        prep_res = {
            "clean_message": "hello",
            "intent": "chat",
            "history_context": "",
            "api_key": "k",
            "model": "m",
        }
        result = node.exec(prep_res)
        assert isinstance(result, str)
        mock_call_llm.assert_called_once()

    def test_exec_calls_llm_for_clarify(self, shared, mock_call_llm):
        node = ChatResponderNode()
        prep_res = {
            "clean_message": "tell me about LeBron",
            "intent": "clarify",
            "history_context": "",
            "api_key": "k",
            "model": "m",
        }
        result = node.exec(prep_res)
        assert isinstance(result, str)
        mock_call_llm.assert_called_once()

    def test_exec_fallback_returns_apology(self):
        node = ChatResponderNode()
        result = node.exec_fallback(None, Exception("fail"))
        assert "sorry" in result.lower() or "try again" in result.lower()

    def test_post_writes_response_and_history(self, shared):
        node = ChatResponderNode()
        node.post(shared, None, "Hello! How can I help?")
        assert shared["response"] == "Hello! How can I help?"
        assert len(shared["chat_history"]) == 1
        assert shared["chat_history"][0]["role"] == "assistant"
        assert shared["chat_history"][0]["sql"] is None
        assert shared["chat_history"][0]["error"] is False
