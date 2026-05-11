import re

import yaml

from utils.call_llm import call_llm

_RE_CODE_FENCE_YAML = re.compile(r"```yaml\s*\n?(.*?)```", re.DOTALL)
_RE_CODE_FENCE_PLAIN = re.compile(r"```\s*\n?(.*?)```", re.DOTALL)
_RE_YAML_KEY_LINE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*:")
_RE_YAML_KV = re.compile(r"^(\s*[a-zA-Z_][a-zA-Z0-9_]*:\s*)(.*)")
_RE_YAML_KV_ANY = re.compile(r"^\s*([a-zA-Z_][a-zA-Z0-9_]*):\s*(.*)")
_RE_FENCE_START = re.compile(r"^```(?:yaml)?\s*")
_RE_FENCE_END = re.compile(r"\s*```$")


def _extract_yaml_block(text: str) -> str | None:
    stripped = text.strip()

    for pattern in (_RE_CODE_FENCE_YAML, _RE_CODE_FENCE_PLAIN):
        match = pattern.search(stripped)
        if match:
            return _fix_yaml_quoting(match.group(1).strip())

    lines = stripped.split("\n")
    yaml_start = -1
    for i, line in enumerate(lines):
        if _RE_YAML_KEY_LINE.match(line):
            yaml_start = i
            break

    if yaml_start > 0:
        return _fix_yaml_quoting("\n".join(lines[yaml_start:]))

    return _fix_yaml_quoting(stripped)


def _fix_yaml_quoting(text: str) -> str:
    lines = text.split("\n")
    fixed: list[str] = []
    for line in lines:
        m = _RE_YAML_KV.match(line)
        if m:
            prefix, value = m.group(1), m.group(2)
            if (
                value
                and not value.startswith(('"', "'", "[", "{", "|", ">", "-"))
                and (":" in value or "#" in value)
            ):
                value = f'"{value}"'
            fixed.append(prefix + value)
        else:
            fixed.append(line)
    return "\n".join(fixed)


def _parse_yaml_safe(text: str) -> dict | None:
    try:
        parsed = yaml.safe_load(text)
        if isinstance(parsed, dict):
            return parsed
    except yaml.YAMLError:
        pass
    return None


def _strip_fences(text: str) -> str:
    result = text.strip()
    result = _RE_FENCE_START.sub("", result)
    result = _RE_FENCE_END.sub("", result)
    return result.strip()


def call_llm_structured(
    prompt: str,
    api_key: str,
    model: str,
    required_fields: list[str],
    system_prompt: str = "",
) -> dict:
    yaml_system_prompt = (
        system_prompt + "\n\nYou must respond with valid YAML only. "
        "Do NOT include markdown code fences. "
        "Do NOT include any other text before or after the YAML. "
        "Your entire response must be parseable as YAML. "
        "IMPORTANT: If any string value contains a colon (:), "
        "wrap that value in double quotes."
    )
    if required_fields:
        yaml_system_prompt += (
            "\n\nThe following fields are REQUIRED: " + ", ".join(required_fields) + "."
        )

    response = call_llm(prompt, api_key, model, yaml_system_prompt)

    block = _extract_yaml_block(response)
    parsed = _parse_yaml_safe(block) if block else None
    if parsed is not None:
        _validate_required_fields(parsed, required_fields)
        return parsed

    rebuilt = _rebuild_yaml(response, required_fields)
    parsed = _parse_yaml_safe(rebuilt)
    if parsed is not None:
        _validate_required_fields(parsed, required_fields)
        return parsed

    cleaned = _strip_fences(response)
    parsed = _parse_yaml_safe(cleaned)
    if parsed is not None:
        _validate_required_fields(parsed, required_fields)
        return parsed

    raise ValueError(
        f"Could not parse LLM response as YAML. Response excerpt: {response[:300]}"
    )


def _rebuild_yaml(text: str, required_fields: list[str]) -> str:
    lines = text.split("\n")
    extracted: dict[str, str] = {}
    current_key: str | None = None
    current_value: list[str] = []

    for line in lines:
        m = _RE_YAML_KV_ANY.match(line)
        if m:
            if current_key:
                extracted[current_key] = "\n".join(current_value).strip()
            current_key = m.group(1)
            rest = m.group(2).strip()
            current_value = [rest] if rest else []
        elif current_key:
            current_value.append(line)

    if current_key:
        extracted[current_key] = "\n".join(current_value).strip()

    if any(field in extracted for field in required_fields):
        yaml_lines: list[str] = []
        for key, value in extracted.items():
            if not isinstance(value, str):
                value = str(value)
            if ":" in value or "#" in value or len(value) > 80:
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                yaml_lines.append(f'{key}: "{escaped}"')
            else:
                yaml_lines.append(f"{key}: {value}")
        return "\n".join(yaml_lines)

    return text


def _validate_required_fields(parsed: dict, required_fields: list[str]) -> None:
    for field in required_fields:
        if field not in parsed:
            raise ValueError(f"Required field '{field}' missing from LLM response")
