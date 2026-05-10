import json
import urllib.request

import httpx
import pytest
import respx

from utils.call_llm import call_llm


@pytest.mark.http_mock
@respx.mock
def test_call_llm_uses_openrouter_chat_completions_endpoint() -> None:
    route = respx.post("https://openrouter.ai/api/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "id": "chatcmpl-test",
                "object": "chat.completion",
                "created": 1,
                "model": "test-model",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Mocked response"},
                    }
                ],
            },
        )
    )

    result = call_llm("Who won?", "test-key", "test-model", system_prompt="Be brief")

    assert result == "Mocked response"
    assert route.called
    payload = json.loads(route.calls.last.request.content)
    assert payload["model"] == "test-model"
    assert payload["messages"] == [
        {"role": "system", "content": "Be brief"},
        {"role": "user", "content": "Who won?"},
    ]


@pytest.mark.http_mock
@pytest.mark.enable_socket(allow_hosts=["127.0.0.1", "localhost"])
def test_pytest_httpserver_can_model_local_http_dependencies(httpserver) -> None:
    httpserver.expect_request("/health").respond_with_json({"status": "ok"})

    with urllib.request.urlopen(httpserver.url_for("/health"), timeout=5) as response:
        body = json.loads(response.read().decode("utf-8"))

    assert body == {"status": "ok"}
