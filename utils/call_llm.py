from typing import Any

from openai import OpenAI
from openai.types.chat import (
    ChatCompletionMessageParam,
    ChatCompletionSystemMessageParam,
    ChatCompletionUserMessageParam,
)


def call_llm(
    prompt: str,
    api_key: str,
    model: str,
    system_prompt: str = "",
) -> str:
    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")
    messages: list[ChatCompletionMessageParam] = []
    if system_prompt:
        messages.append(
            ChatCompletionSystemMessageParam(role="system", content=system_prompt)
        )
    messages.append(ChatCompletionUserMessageParam(role="user", content=prompt))
    r: Any = client.chat.completions.create(model=model, messages=messages)
    content = r.choices[0].message.content
    assert content is not None
    return content
