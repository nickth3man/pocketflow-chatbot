# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

**Package manager:** `uv` (lockfile: `uv.lock`, Python ≥ 3.12)

```bash
uv sync                          # Install all deps (runtime + dev)
uv add <package>                 # Add a runtime dependency
uv add --dev <package>           # Add a dev dependency
uv run python app.py             # Run the Gradio web UI
uv run python main.py            # Run the CLI chat interface
```

### Lint & Format (ruff)

```bash
uv run ruff check .              # Lint
uv run ruff check --fix .        # Lint + auto-fix
uv run ruff format .             # Format
uv run ruff format --check .     # Check formatting (CI)
```

### Type Check

```bash
uv run ty check .                # Fast check with ty (development)
uv run python -m pyright .       # Full check with pyright (use -m to avoid pyenv shim issues on Windows)
```

### Test (pytest)

Prefer `uv run python -m pytest` over `uv run pytest` on Windows to avoid console-script path issues.

```bash
uv run python -m pytest                              # Run all tests
uv run python -m pytest -v                           # Verbose
uv run python -m pytest -k "keyword"                 # Filter by name
uv run python -m pytest tests/test_utils.py          # Single file
uv run python -m pytest -n auto                      # Parallel (pytest-xdist)
uv run python -m pytest -m "not slow"                # Skip slow tests
uv run python -m pytest -m "not slow and not live_api"  # Skip slow + live API tests
uv run python -m pytest -m live_api                  # Live OpenRouter API tests only
uv run python -m pytest -m property                  # Hypothesis property tests
uv run python -m pytest -m http_mock                 # Mocked/local HTTP tests
uv run python -m pytest -m recording                 # Cassette-backed HTTP tests
uv run python -m pytest -m benchmark                 # Benchmark tests
uv run python -m pytest --snapshot-update            # Regenerate syrupy snapshots
uv run python -m pytest --count=5                    # Repeat each test 5× (pytest-repeat)
uv run python -m pytest --picked                     # Tests from modified files only
uv run python -m pytest --testmon                    # Tests affected by changes only
uv run python -m pytest --randomly-seed=last         # Rerun with same random seed
uv run python -m pytest --dead-fixtures              # List unused fixtures
uv run python -m pytest --ruff --ruff-format         # Lint + format check via pytest
uv run python -m pytest --codeblocks                 # Test code blocks in READMEs
uv run python -m pytest --duration=10                # Show 10 slowest tests
uv run python -m pytest --report-log reportlog.jsonl # Structured test log
uv run pytest-duration-insights explore reportlog.jsonl  # Interactive dashboard
```

### CI pipeline

```bash
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run python -m pyright . && uv run python -m pytest
```

**Required `.env` file** (see `.env.example`):
```
OPENROUTER_API_KEY=sk-or-v1-...
OPENROUTER_MODEL=openai/gpt-4o
# DUCKDB_PATH=path/to/nba.duckdb   # defaults to test-db/nba.duckdb
# DB_QUERY_TIMEOUT=30
```

## Architecture

This is a **PocketFlow-based** NBA chatbot that translates natural language questions into DuckDB SQL queries against a local `nba.duckdb` database, then narrates the results.

### Flow engine

PocketFlow organises work as a graph of `Node` subclasses linked by action strings. Each node has three stages:
- `prep(shared)` — reads from the shared dict and returns typed prep data
- `exec(prep_res)` — pure computation (LLM call, DB query, etc.)
- `post(shared, prep_res, exec_res)` — writes results back to shared and returns the next action string

The main flow (`flow.py → create_chat_flow()`) is wired as a DAG:

```
MessagePreprocessor → HistoryContextBuilder → IntentClassifier
                                                      │
                            ├─── "chat"/"clarify" ───►│──► ChatResponder
                            │
                            └─── "query_db" ──────────►│
                                                        │
                                              TableSelector → QueryPlanner → SQLGenerator
                                                                                    │
                                                                             SQLValidator
                                                                               ├──┤ "default"
                                                                               │  └──► SQLExecutor
                                                                               │        ├──┤ "success"
                                                                               │        │  └──► ResultAnalyzer → ResponseBuilder
                                                                               │        │
                                                                               │        └──── "error"
                                                                               │             │
                                                                               │    ErrorRecoveryFlow (nested):
                                                                               │    ErrorAnalyzer → SchemaRecheck
                                                                               │    → SQLFixer → FixValidator
                                                                               │    → RecoveryDecision
                                                                               │         │
                                                                               │    "retry" ──► SQLExecutor (re-execute fixed SQL)
                                                                               │    "give_up" ─► ResultAnalyzer
                                                                               │
                                                                               └──┤ "error"
                                                                                  └──► ErrorRecoveryFlow
```

### Shared dict

All node state flows through a single `shared: dict[str, Any]`. Key fields:
- `user_message`, `clean_message`, `entities` — raw and preprocessed input
- `intent` — `"query_db"`, `"chat"`, or `"clarify"`
- `schema_by_table`, `schema_context` — DuckDB schema loaded at startup
- `generated_sql`, `sql_result` — SQL and execution results
- `debug_attempts`, `max_debug_attempts` — error-recovery counters, reset to `0`/`3` by `MessagePreprocessorNode` at the start of every turn
- `response` — final markdown string rendered in the UI
- `step_logs` — list of `{node, status, summary}` dicts shown in the sidebar
- `chat_history` — running message list (pruned to 100 entries)

### LLM calls

All LLM calls go through OpenRouter via the `openai` SDK (`utils/call_llm.py`, `utils/call_llm_structured.py`). `call_llm_structured` expects the model to return valid JSON matching `required_fields`; it retries on parse failure.

### Prompts

Every node that calls an LLM loads its system prompt from `prompts/<name>.txt` on demand via `get_prompt_cached(name)`. Edit prompt files to change model behaviour without touching node code.

### Entry points

- **`app.py`** — Gradio UI. Runs the flow in a background thread and streams step-trace updates to the sidebar while waiting. Also handles chart generation (`_try_generate_chart`) and metadata display.
- **`main.py`** — Simple REPL CLI for the same flow.

### Utils

| File | Purpose |
|------|---------|
| `call_llm.py` | Raw LLM call via OpenRouter |
| `call_llm_structured.py` | JSON-extracting LLM call with retry |
| `execute_query.py` | DuckDB query execution with timeout |
| `get_full_schema.py` | Reads all table schemas from DuckDB |
| `format_schema.py` | Formats schema dict for prompt injection |
| `get_schema_subset.py` | Filters schema to selected tables |
| `validate_sql_safety.py` | Rejects non-SELECT or destructive SQL |
| `optimize_sql.py` | Appends `LIMIT 200` if absent and adds trailing semicolon |
| `classify_error.py` | Categorises DuckDB error strings |
| `format_results_table.py` | Markdown table from query results |
| `format_response_markdown.py` | Assembles final response with SQL collapsible |

## Tests

Tests live in `tests/`. `conftest.py` provides shared fixtures. Snapshots (syrupy) are in `tests/__snapshots__/`. See [docs/testing.md](docs/testing.md) for the full pytest plugin playbook.

Most tests mock LLM calls and the database. Network is blocked by `pytest-socket` by default; `openrouter.ai` is whitelisted. Tests needing other hosts add `@pytest.mark.enable_socket(allow_hosts=['...'])`.

## Conventions

- Each `Node` subclass declares a `NODE_LABEL: str` class attribute that drives the `step_logs` display name and all `_log_step` calls inside that class. Keep it short (one word or PascalCase) — it appears in the UI sidebar. Never pass a raw string literal to `_log_step` as the node name; always use `self.NODE_LABEL`.
- `SQLGeneratorNode` validates SQL safety twice: in the `exec` stage on the raw LLM output (enables retry via `max_retries`), and in the `post` stage after `optimize_sql` (belt-and-suspenders on the final SQL). `optimize_sql` only adds `LIMIT`/semicolon so this second check should never fire, but it guards against future changes to that function.
- Assistant turns are appended to `chat_history` via the `_append_assistant_turn` helper (`nodes.py`). Both `ResponseBuilderNode` and `ChatResponderNode` use this helper — do not open-code the dict append in new paths.
- **ruff** handles both linting and formatting — don't use other formatters
- **ty** for fast type-check during development, **pyright** for comprehensive checks
- Type annotations required on all function signatures
- Use `pytest_check.check` (imported as `check`) for multi-assertion integration tests so all failures surface in one run
- Snapshot tests with **syrupy** lock output structure; regenerate with `--snapshot-update`
- Use `@pytest.mark.freeze_time('YYYY-MM-DD')` for tests that depend on `datetime` or `time.time`
- `pytest-modified-env` auto-fails tests that leak `os.environ` changes; add `@pytest.mark.modify_env()` to opt out

### Choosing a pytest plugin for new tests

- **Hypothesis** (`@pytest.mark.property`): generated strategies for SQL validation/optimization, LLM JSON parsing, markdown/table formatting
- **RESPX** (`@pytest.mark.http_mock`, `@respx.mock`): OpenRouter/OpenAI SDK HTTPX unit tests; assert request payloads without real sockets
- **pytest-httpserver** (`@pytest.mark.http_mock` + `enable_socket` for localhost): when a real local HTTP server is clearer than mocking HTTPX internals
- **pytest-recording** (`@pytest.mark.recording`): cassette-backed OpenRouter integration tests; default replay mode is safe, record new cassettes with `--record-mode=once`
- **pytest-benchmark** (`@pytest.mark.benchmark`): performance-sensitive DuckDB queries, SQL optimization, schema formatting, result rendering
- **pytest-socket**: keep external network blocked by default; live API tests must be marked `live_api` and allow only exact hosts needed
- **pytest-randomly** + **pytest-repeat**: use `--count=5 --randomly-seed=last` to expose ordering/flakiness
- **pytest-picked** or **pytest-testmon**: quick feedback on modified code before the full suite
- **pytest-deadfixtures**: run after fixture-heavy changes to remove unused fixtures
- **pytest-reportlog** + **pytest-duration-insights**: diagnose slow, flaky, or order-dependent tests

### Workflow

After changing tests, run the narrowest relevant command first, then `uv run ruff check .`, `uv run ruff format --check .`, and `uv run python -m pytest` before handing off.

After changing test dependencies, plugin configuration, fixtures, or shared test helpers, also run `uv run ty check .` and `uv run python -m pyright .`.
