# pocketflow-chatbot

NBA Basketball Chatbot built with PocketFlow, DuckDB, and Gradio.

## Dev Environment

- **Package manager**: uv — all commands via `uv run ...`
- **Python**: 3.12+ (`.python-version` pins 3.12)
- **Deps**: `uv sync` to install everything (runtime + dev)

## Commands

```sh
uv sync                          # Install all deps (run after cloning or pulling new deps)
uv add <package>                 # Add a runtime dependency
uv add --dev <package>           # Add a dev dependency
uv run python <file.py>          # Run any Python file
```

### Lint & Format (ruff)

```sh
uv run ruff check .              # Lint all .py files
uv run ruff check --fix .        # Lint + auto-fix
uv run ruff format .             # Format all .py files
uv run ruff format --check .     # Check formatting (CI use)
```

### Type Check (ty + pyright)

```sh
uv run ty check .                # Fast type-check with ty
uv run python -m pyright .       # Full type-check with pyright (use `python -m` to avoid pyenv shim issues on Windows)
```

### Test (pytest)

```sh
uv run python -m pytest                    # Run all tests
uv run python -m pytest -v                 # Run all tests (verbose)
uv run python -m pytest -k "keyword"       # Run tests matching keyword
uv run python -m pytest tests/test_file.py # Run a specific test file
uv run python -m pytest -n auto            # Parallel execution (pytest-xdist)
uv run python -m pytest -m "not slow"      # Skip slow tests
uv run python -m pytest -m live_api        # Run live API tests only
uv run python -m pytest -m property        # Run property-based tests (Hypothesis)
uv run python -m pytest -m http_mock       # Run mocked/local HTTP tests
uv run python -m pytest -m recording       # Run cassette-backed HTTP tests
uv run python -m pytest -m benchmark       # Run benchmark tests
uv run python -m pytest --count=5          # Repeat each test 5 times (pytest-repeat)
uv run python -m pytest --picked           # Run tests from modified files only (pytest-picked)
uv run python -m pytest --testmon          # Run only tests affected by changes (pytest-testmon)
uv run python -m pytest --randomly-seed=last  # Rerun with same random seed (pytest-randomly)
uv run python -m pytest --snapshot-update  # Update all syrupy snapshots
uv run python -m pytest --dead-fixtures    # List unused fixtures (pytest-deadfixtures)
uv run python -m pytest --ruff --ruff-format # Lint + format check via pytest (pytest-ruff)
uv run python -m pytest --codeblocks       # Test code blocks in READMEs (pytest-codeblocks)
uv run python -m pytest --duration=10      # Show 10 slowest tests
uv run python -m pytest --report-log reportlog.jsonl  # Write structured test log (pytest-reportlog)
uv run pytest-duration-insights explore reportlog.jsonl  # Interactive dashboard
```

### All Checks (CI pipeline)

```sh
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run python -m pyright . && uv run python -m pytest
```

## Conventions

- **ruff** handles both linting and formatting — don't use other formatters
- **ty** for fast type-check during development, **pyright** for comprehensive checks
- **pytest** for all testing; tests live in `tests/`
- See [docs/testing.md](docs/testing.md) for the full pytest plugin playbook and command recipes
- Prefer `uv run python -m pytest` over `uv run pytest` on Windows; it avoids console-script path issues
- Type annotations required on all function signatures
- Use `pytest_check.check` (imported as `check`) for multi-assertion integration tests so all failures surface in one run
- Snapshot tests with **syrupy** lock output structure; regenerate with `--snapshot-update`
- Sockets allowed for `openrouter.ai` by default; tests needing other hosts add `@pytest.mark.enable_socket(allow_hosts=['...'])`
- Use `@pytest.mark.freeze_time('YYYY-MM-DD')` for tests that depend on `datetime` or `time.time`
- `pytest-modified-env` auto-fails tests that leak `os.environ` changes; add `@pytest.mark.modify_env()` to opt out
- When creating or editing tests, use the pytest plugin that best fits the behavior instead of hand-rolling helpers:
  - **Hypothesis**: use `@pytest.mark.property` and generated strategies for SQL validation/optimization, YAML-ish LLM parsing, markdown/table formatting, and other input-space-heavy utilities
  - **RESPX**: use `@pytest.mark.http_mock` and `@respx.mock` for OpenRouter/OpenAI SDK HTTPX unit tests; assert request payloads and mocked API responses without real sockets
  - **pytest-httpserver**: use `@pytest.mark.http_mock` plus `@pytest.mark.enable_socket(allow_hosts=['127.0.0.1', 'localhost'])` when a real local HTTP server is clearer than mocking HTTPX internals
  - **pytest-recording**: use `@pytest.mark.recording` for cassette-backed OpenRouter integration tests; default replay mode is safe, and new cassettes should be recorded intentionally with `--record-mode=once`
  - **pytest-benchmark**: use `@pytest.mark.benchmark` for performance-sensitive DuckDB queries, SQL optimization, schema formatting, and result rendering
  - **pytest-socket**: keep external network blocked by default; live API tests must be marked `live_api` and allow only the exact hosts needed
  - **pytest-randomly** and **pytest-repeat**: rerun changed or suspicious tests with `--count=5 --randomly-seed=last` to expose ordering/flakiness
  - **pytest-picked** or **pytest-testmon**: use these for quick feedback on modified code before running the full suite
  - **pytest-deadfixtures**: run after fixture-heavy changes to remove unused or duplicated fixtures
  - **pytest-reportlog** and **pytest-duration-insights**: use these when diagnosing slow, flaky, or order-dependent tests
- After changing tests, run the narrowest relevant command first, then `uv run ruff check .`, `uv run ruff format --check .`, and `uv run python -m pytest` before handing off
- After changing test dependencies, plugin configuration, fixtures, or shared test helpers, also run `uv run ty check .` and `uv run python -m pyright .`
