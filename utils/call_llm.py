import logging
import time

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)

_logger = logging.getLogger("nba_chatbot")


def call_llm(
    prompt: str,
    api_key: str,
    model: str,
    system_prompt: str = "",
) -> str:
    client = OpenAI(
        api_key=api_key,
        base_url="https://openrouter.ai/api/v1",
        timeout=60.0,
    )
    messages: list[ChatCompletionMessageParam] = []
    if system_prompt:
        messages.append(
            ChatCompletionSystemMessageParam(role="system", content=system_prompt)
        )
    messages.append(ChatCompletionUserMessageParam(role="user", content=prompt))

    start = time.monotonic()
    prompt_chars = len(prompt)

    _logger.debug(
        "[LLM] requesting %s — prompt=%d chars, %d messages",
        model,
        prompt_chars,
        len(messages),
    )

    try:
        r = client.chat.completions.create(model=model, messages=messages)
    except Exception as e:
        elapsed_ms = (time.monotonic() - start) * 1000
        _logger.warning(
            "[LLM] %s ✗ request failed after %.0fms: %s",
            model,
            elapsed_ms,
            str(e)[:200],
            extra={
                "llm_model": model,
                "llm_prompt_chars": prompt_chars,
                "llm_duration_ms": round(elapsed_ms, 1),
                "llm_success": False,
                "llm_error": str(e)[:200],
                "duration_ms": round(elapsed_ms, 1),
                "success": False,
            },
        )
        raise

    elapsed_ms = (time.monotonic() - start) * 1000

    if not r.choices:
        raise ValueError("LLM returned no choices")

    content = r.choices[0].message.content
    if content is None:
        raise ValueError("LLM returned null content")

    total_tokens = 0
    prompt_tokens = 0
    completion_tokens = 0
    if r.usage is not None:
        prompt_tokens = r.usage.prompt_tokens or 0
        completion_tokens = r.usage.completion_tokens or 0
        total_tokens = r.usage.total_tokens or 0

    finish_reason = str(r.choices[0].finish_reason or "unknown")
    response_preview = content[:120].replace("\n", " ")

    _logger.info(
        "[LLM] %s ✓ %d tok in %.0fms (in=%d out=%d finish=%s): %s",
        model,
        total_tokens,
        elapsed_ms,
        prompt_tokens,
        completion_tokens,
        finish_reason,
        response_preview,
        extra={
            "llm_model": model,
            "llm_prompt_chars": prompt_chars,
            "llm_response_chars": len(content),
            "llm_duration_ms": round(elapsed_ms, 1),
            "llm_prompt_tokens": prompt_tokens,
            "llm_completion_tokens": completion_tokens,
            "llm_total_tokens": total_tokens,
            "llm_finish_reason": finish_reason,
            "duration_ms": round(elapsed_ms, 1),
            "success": True,
            "total_tokens": total_tokens,
        },
    )
    return content
