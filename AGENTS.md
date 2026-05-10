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
uv run pyright .                 # Full type-check with pyright
```

### Test (pytest)

```sh
uv run pytest                    # Run all tests
uv run pytest -v                 # Run all tests (verbose)
uv run pytest -k "keyword"       # Run tests matching keyword
uv run pytest tests/test_file.py # Run a specific test file
uv run pytest -n auto            # Parallel execution (pytest-xdist)
uv run pytest -m "not slow"      # Skip slow tests
uv run pytest -m live_api        # Run live API tests only
uv run pytest --count=5          # Repeat each test 5 times (pytest-repeat)
uv run pytest --picked           # Run tests from modified files only (pytest-picked)
uv run pytest --testmon          # Run only tests affected by changes (pytest-testmon)
uv run pytest --randomly-seed=last  # Rerun with same random seed (pytest-randomly)
uv run pytest --snapshot-update  # Update all syrupy snapshots
uv run pytest --dead-fixtures    # List unused fixtures (pytest-deadfixtures)
uv run pytest --ruff --ruff-format # Lint + format check via pytest (pytest-ruff)
uv run pytest --codeblocks       # Test code blocks in READMEs (pytest-codeblocks)
uv run pytest --duration=10      # Show 10 slowest tests
uv run pytest --report-log reportlog.jsonl  # Write structured test log (pytest-reportlog)
uv run pytest-duration-insights explore reportlog.jsonl  # Interactive dashboard
```

### All Checks (CI pipeline)

```sh
uv run ruff check . && uv run ruff format --check . && uv run ty check . && uv run pyright . && uv run pytest
```

## Conventions

- **ruff** handles both linting and formatting — don't use other formatters
- **ty** for fast type-check during development, **pyright** for comprehensive checks
- **pytest** for all testing; tests live in `tests/`
- Type annotations required on all function signatures
- Use `pytest_check.check` (imported as `check`) for multi-assertion integration tests so all failures surface in one run
- Snapshot tests with **syrupy** lock output structure; regenerate with `--snapshot-update`
- Sockets allowed for `openrouter.ai` by default; tests needing other hosts add `@pytest.mark.enable_socket(allow_hosts=['...'])`
- Use `@pytest.mark.freeze_time('YYYY-MM-DD')` for tests that depend on `datetime` or `time.time`
- `pytest-modified-env` auto-fails tests that leak `os.environ` changes; add `@pytest.mark.modify_env()` to opt out
