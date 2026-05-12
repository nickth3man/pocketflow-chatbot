"""Tests for call_llm and call_llm_structured."""

import pytest

from utils.call_llm import call_llm
from utils.call_llm_structured import (
    _parse_yaml_safe,
    _validate_required_fields,
    call_llm_structured,
)


class TestCallLlm:
    def test_call_llm_success(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.chat.completions.create.return_value = mocker.MagicMock(
            choices=[mocker.MagicMock(message=mocker.MagicMock(content="Hello"))]
        )
        mocker.patch("utils.call_llm.OpenAI", return_value=mock_client)
        result = call_llm("test prompt", "test-api-key", "test-model")
        assert result == "Hello"

    def test_call_llm_no_choices(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.chat.completions.create.return_value = mocker.MagicMock(choices=[])
        mocker.patch("utils.call_llm.OpenAI", return_value=mock_client)
        with pytest.raises(ValueError, match="no choices"):
            call_llm("test prompt", "test-api-key", "test-model")

    def test_call_llm_null_content(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.chat.completions.create.return_value = mocker.MagicMock(
            choices=[mocker.MagicMock(message=mocker.MagicMock(content=None))]
        )
        mocker.patch("utils.call_llm.OpenAI", return_value=mock_client)
        with pytest.raises(ValueError, match="null content"):
            call_llm("test prompt", "test-api-key", "test-model")

    def test_call_llm_with_system_prompt(self, mocker):
        mock_client = mocker.MagicMock()
        mock_client.chat.completions.create.return_value = mocker.MagicMock(
            choices=[mocker.MagicMock(message=mocker.MagicMock(content="Response"))]
        )
        mocker.patch("utils.call_llm.OpenAI", return_value=mock_client)
        result = call_llm("prompt", "key", "model", system_prompt="Be helpful")
        assert result == "Response"


class TestCallLlmStructured:
    def test_simple_yaml_response(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="intent: query_db\nreason: needs data",
        )
        result = call_llm_structured("prompt", "key", "model", ["intent", "reason"])
        assert result == {"intent": "query_db", "reason": "needs data"}

    def test_yaml_with_code_fences(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="Here is the answer:\n```yaml\nintent: query_db\nreason: user asked\n```",
        )
        result = call_llm_structured("prompt", "key", "model", ["intent", "reason"])
        assert result == {"intent": "query_db", "reason": "user asked"}

    def test_yaml_with_colon_in_value_quoted(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value='thinking: "SQL query: select all"\nsql: SELECT 1',
        )
        result = call_llm_structured("prompt", "key", "model", ["thinking", "sql"])
        assert result == {"thinking": "SQL query: select all", "sql": "SELECT 1"}

    def test_yaml_with_colon_in_value_unquoted(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="reason: need to: fix this\nstatus: ok",
        )
        result = call_llm_structured("prompt", "key", "model", ["reason", "status"])
        assert result == {"reason": "need to: fix this", "status": "ok"}

    def test_rebuild_yaml_fallback(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="Some prefix text\nthinking: This is a complex analysis with colons\nsql: SELECT 1\n",
        )
        result = call_llm_structured("prompt", "key", "model", ["thinking", "sql"])
        assert "thinking" in result
        assert "sql" in result

    def test_missing_required_field_raises(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="unrelated: text",
        )
        with pytest.raises(ValueError, match=r"Required fields.*required_field.*missing"):
            call_llm_structured("prompt", "key", "model", ["required_field"])

    def test_parse_yaml_safe_valid(self):
        result = _parse_yaml_safe("key: value\nnum: 42")
        assert result == {"key": "value", "num": 42}

    def test_parse_yaml_safe_invalid(self):
        result = _parse_yaml_safe("not: : : valid: yaml")
        assert result is None

    def test_parse_yaml_safe_not_dict(self):
        result = _parse_yaml_safe("- item1\n- item2")
        assert result is None

    def test_validate_required_fields_passes(self):
        _validate_required_fields({"a": 1, "b": 2}, ["a", "b"])

    def test_validate_required_fields_raises(self):
        with pytest.raises(ValueError, match=r"Required fields.*missing.*missing from"):
            _validate_required_fields({"a": 1}, ["a", "missing"])

    def test_unparseable_response_raises(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="This is plain text with no YAML structure whatsoever.",
        )
        with pytest.raises(ValueError, match="Could not parse LLM response as YAML"):
            call_llm_structured("prompt", "key", "model", ["intent"])

    def test_call_llm_structured_empty_required_fields(self, mocker):
        mocker.patch(
            "utils.call_llm_structured.call_llm",
            return_value="key: value",
        )
        result = call_llm_structured("prompt", "key", "model", [])
        assert result == {"key": "value"}
