import logging
import os
import sys
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from flow import chat_flow
from utils.get_full_schema import get_full_schema
from utils.logging_setup import setup_logging

setup_logging()
_logger = logging.getLogger("nba_chatbot")

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "test-db" / "nba.duckdb")


def build_shared() -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY is not set.", file=sys.stderr)
        print(
            "Create a .env file with: OPENROUTER_API_KEY=sk-or-v1-...", file=sys.stderr
        )
        raise SystemExit(1)

    model = os.environ.get("OPENROUTER_MODEL")
    if not model:
        print("ERROR: OPENROUTER_MODEL is not set.", file=sys.stderr)
        print(
            "Create a .env file with: OPENROUTER_MODEL=openai/gpt-4o", file=sys.stderr
        )
        raise SystemExit(1)

    db_path = os.environ.get("DUCKDB_PATH", _DEFAULT_DB_PATH)
    db_query_timeout = int(os.environ.get("DB_QUERY_TIMEOUT", "30"))

    if not os.path.isfile(db_path):
        print(f"ERROR: Database not found at: {db_path}", file=sys.stderr)
        print(
            "Set DUCKDB_PATH in .env to point to your nba.duckdb file.", file=sys.stderr
        )
        raise SystemExit(1)

    schema_by_table = get_full_schema(db_path)

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
            continue

        shared["user_message"] = user_input
        shared["step_logs"] = []
        shared["chat_history"].append({
            "role": "user",
            "content": user_input,
            "sql": None,
            "error": False,
        })
        chat_flow.run(shared)
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
