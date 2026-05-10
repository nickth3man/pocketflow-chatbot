# Testing Setup

This project uses pytest as the test runner and keeps plugin usage explicit through
markers, focused fixtures, and opt-in commands.

## Everyday Commands

```sh
uv run python -m pytest
uv run python -m pytest -m "not slow"
uv run python -m pytest --picked
uv run python -m pytest --testmon
uv run python -m pytest -n auto
```

Use `python -m pytest` on Windows if the `pytest` console script reports
`Failed to canonicalize script path`.

## Plugin Playbook

Use `hypothesis` for input spaces that are easy to describe but annoying to
cover with examples: SQL strings, table rows, YAML-ish LLM output, and markdown
formatting. Mark these tests with `@pytest.mark.property`. The default Hypothesis
profile runs 100 examples; CI can run a deeper profile with:

```sh
$env:HYPOTHESIS_PROFILE = "ci"
uv run python -m pytest -m property
```

Use `respx` for OpenRouter/OpenAI SDK unit tests. It intercepts HTTPX requests
without opening sockets, which keeps API behavior testable and deterministic.
Prefer it when you need to assert request payloads, headers, retry behavior, or
API error responses.

Use `pytest-httpserver` when a real local HTTP server is more realistic than an
HTTPX mock. Mark these tests with both `@pytest.mark.http_mock` and
`@pytest.mark.enable_socket(allow_hosts=["127.0.0.1", "localhost"])`.

Use `pytest-recording` for cassette-backed integration tests against OpenRouter.
The shared `vcr_config` fixture scrubs auth-like headers and query parameters,
ignores localhost, and defaults to replay-only mode. Record intentionally:

```sh
uv run python -m pytest -m recording --record-mode=once
uv run python -m pytest -m recording
```

Use `pytest-benchmark` for performance-sensitive utilities, especially DuckDB
queries, schema formatting, SQL optimization, and result table rendering. Mark
benchmarks with `@pytest.mark.benchmark` and compare runs with:

```sh
uv run python -m pytest -m benchmark --benchmark-autosave
uv run python -m pytest -m benchmark --benchmark-compare
```

## Existing Plugin Habits

Use `pytest-socket` to keep accidental network calls out of tests. Only live API
tests should opt in with `@pytest.mark.live_api` and a narrow `enable_socket`
host list.

Use `syrupy` snapshots for structured, human-reviewed output. Update snapshots
only when the behavior change is intentional:

```sh
uv run python -m pytest --snapshot-update
```

Use `pytest-check` for integration tests where several assertions should be
reported together. Use `pytest-modified-env` to catch leaked environment changes;
tests that intentionally mutate env vars need `@pytest.mark.modify_env()`.

Use `pytest-repeat` and `pytest-randomly` together to flush out order dependence:

```sh
uv run python -m pytest --count=5 --randomly-seed=last
```

Use `pytest-reportlog` and `pytest-duration-insights` when investigating slow or
unstable tests:

```sh
uv run python -m pytest --report-log reportlog.jsonl
uv run pytest-duration-insights explore reportlog.jsonl
```
