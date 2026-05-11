import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from flow import chat_flow
from utils.get_full_schema import get_full_schema
from utils.logging_setup import setup_logging

setup_logging(prefix="cli")
logger = logging.getLogger("nba_chatbot")

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "test-db" / "nba.duckdb")


def build_shared() -> dict[str, Any]:
    logger.debug("build_shared: starting initialization")

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        logger.critical("OPENROUTER_API_KEY environment variable is not set")
        print("ERROR: OPENROUTER_API_KEY is not set.", file=sys.stderr)
        print(
            "Create a .env file with: OPENROUTER_API_KEY=sk-or-v1-...", file=sys.stderr
        )
        raise SystemExit(1)
    logger.debug("build_shared: OPENROUTER_API_KEY loaded")

    model = os.environ.get("OPENROUTER_MODEL")
    if not model:
        logger.critical("OPENROUTER_MODEL environment variable is not set")
        print("ERROR: OPENROUTER_MODEL is not set.", file=sys.stderr)
        print(
            "Create a .env file with: OPENROUTER_MODEL=openai/gpt-4o", file=sys.stderr
        )
        raise SystemExit(1)
    logger.debug("build_shared: OPENROUTER_MODEL loaded: %s", model)

    db_path_raw = os.environ.get("DUCKDB_PATH", _DEFAULT_DB_PATH)
    db_path = (
        str(_PROJECT_ROOT / db_path_raw)
        if not os.path.isabs(db_path_raw)
        else db_path_raw
    )
    logger.debug("build_shared: resolved db_path=%s", db_path)
    db_query_timeout = int(os.environ.get("DB_QUERY_TIMEOUT", "30"))

    if not os.path.isfile(db_path):
        logger.critical("Database file not found at: %s", db_path)
        print(f"ERROR: Database not found at: {db_path}", file=sys.stderr)
        print(
            "Set DUCKDB_PATH in .env to point to your nba.duckdb file.", file=sys.stderr
        )
        raise SystemExit(1)
    logger.info("Database found: %s", db_path)

    logger.debug("build_shared: loading schema...")
    schema_by_table = get_full_schema(db_path)
    logger.info("Schema loaded: %d tables", len(schema_by_table))
    for tname, info in schema_by_table.items():
        logger.debug(
            "  table=%s cols=%d rows=%d",
            tname,
            len(info.get("columns", [])),
            info.get("row_count", 0),
        )

    return {
        "db_path": db_path,
        "schema_by_table": schema_by_table,
        "openrouter_api_key": api_key,
        "openrouter_model": model,
        "db_query_timeout": db_query_timeout,
        "max_rows": 200,
        "chat_history": [],
    }


def main() -> None:
    shared = build_shared()
    print("NBA Basketball Chatbot (CLI)")
    print("Type 'quit' to exit.")
    print()

    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if user_input.lower() in ("quit", "exit", "q"):
            break

        if not user_input:
            print("Please enter a question about NBA basketball.")
            continue

        shared["user_message"] = user_input
        shared["step_logs"] = []
        shared["chat_history"].append({
            "role": "user",
            "content": user_input,
            "sql": None,
            "error": False,
        })
        try:
            chat_flow.run(shared)
        except Exception as e:
            logger.error("Flow crashed: %s", e)
            shared["response"] = (
                "Sorry, an unexpected error occurred. Please try rephrasing your question."
            )
        response = shared.get("response", "Sorry, I couldn't generate a response.")

        print("\n── Step Trace ──────────────────────────────")
        for entry in shared.get("step_logs", []):
            icon = "✓" if entry.get("status") == "complete" else "✗"
            print(f"  {icon} [{entry.get('node', '?')}] {entry.get('summary', '')}")
        print("─────────────────────────────────────────────")
        print(f"Bot: {response}")
        print()


if __name__ == "__main__":
    main()
