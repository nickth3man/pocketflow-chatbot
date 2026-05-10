"""Tests for pre-processing nodes: MessagePreprocessor, HistoryContextBuilder, IntentClassifier."""

from nodes import (
    HistoryContextBuilderNode,
    IntentClassifierNode,
    MessagePreprocessorNode,
)


class TestMessagePreprocessorNode:
    def test_prep_reads_shared(self, shared):
        shared["user_message"] = "Who scored the most?"
        shared["openrouter_api_key"] = "key"
        shared["openrouter_model"] = "model"
        node = MessagePreprocessorNode()
        result = node.prep(shared)
        assert result["user_message"] == "Who scored the most?"
        assert result["api_key"] == "key"
        assert result["model"] == "model"

    def test_exec_calls_llm_structured(self, shared, mock_call_llm_structured):
        shared["user_message"] = "Tell me about LeBron"
        node = MessagePreprocessorNode()
        result = node.exec({
            "user_message": "Tell me about LeBron",
            "api_key": "k",
            "model": "m",
            "system_prompt": "",
        })
        assert "clean_message" in result
        assert "entities" in result
        mock_call_llm_structured.assert_called_once()

    def test_post_writes_shared(self, shared):
        shared["user_message"] = "test"
        node = MessagePreprocessorNode()
        exec_res = {
            "clean_message": "test query",
            "entities": {"players": ["LeBron"], "teams": [], "seasons": []},
        }
        node.post(shared, None, exec_res)
        assert shared["clean_message"] == "test query"
        assert shared["entities"] == {"players": ["LeBron"], "teams": [], "seasons": []}

    def test_exec_fallback(self):
        node = MessagePreprocessorNode()
        assert hasattr(node, "exec_fallback")


class TestHistoryContextBuilderNode:
    def test_prep_reads_last_6(self, shared):
        shared["chat_history"] = [
            {"role": "user", "content": f"msg{i}", "sql": None} for i in range(10)
        ]
        node = HistoryContextBuilderNode()
        result = node.prep(shared)
        assert len(result) == 6

    def test_exec_empty_history(self, shared):
        shared["chat_history"] = []
        node = HistoryContextBuilderNode()
        result = node.exec([])
        assert result == ""

    def test_exec_formats_with_sql(self):
        node = HistoryContextBuilderNode()
        history = [
            {"role": "user", "content": "Who scored the most?", "sql": None},
            {
                "role": "assistant",
                "content": "Here are the results",
                "sql": "SELECT * FROM dim_player",
            },
        ]
        result = node.exec(history)
        assert "[user:" in result
        assert "[assistant:" in result
        assert "SQL:" in result

    def test_post_writes_context(self, shared):
        node = HistoryContextBuilderNode()
        node.post(shared, None, "context string")
        assert shared["history_context"] == "context string"


class TestIntentClassifierNode:
    def test_prep_reads_shared(self, shared):
        shared["clean_message"] = "test"
        shared["history_context"] = ""
        shared["openrouter_api_key"] = "key"
        shared["openrouter_model"] = "m"
        node = IntentClassifierNode()
        result = node.prep(shared)
        assert result["clean_message"] == "test"

    def test_exec_calls_llm_structured(self, shared, mock_call_llm_structured):
        mock_call_llm_structured.return_value = {
            "intent": "query_db",
            "reason": "needs stats",
        }
        node = IntentClassifierNode()
        prep_res = {
            "clean_message": "test",
            "history_context": "",
            "api_key": "k",
            "model": "m",
            "system_prompt": "",
        }
        result = node.exec(prep_res)
        assert result["intent"] == "query_db"
        mock_call_llm_structured.assert_called_once()

    def test_post_writes_intent_and_returns_action(self, shared):
        node = IntentClassifierNode()
        result = node.post(shared, None, {"intent": "query_db", "reason": "stats"})
        assert shared["intent"] == "query_db"
        assert shared["debug_attempts"] == 0
        assert shared["max_debug_attempts"] == 3
        assert result == "query_db"

    def test_post_returns_chat_action(self, shared):
        node = IntentClassifierNode()
        result = node.post(shared, None, {"intent": "chat", "reason": "general"})
        assert result == "chat"

    def test_post_returns_clarify_action(self, shared):
        node = IntentClassifierNode()
        result = node.post(shared, None, {"intent": "clarify", "reason": "ambiguous"})
        assert result == "clarify"
