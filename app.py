import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any, Generator

import gradio as gr
from dotenv import load_dotenv

from flow import chat_flow
from utils.get_full_schema import get_full_schema
from utils.logging_setup import setup_logging

logger = setup_logging()

load_dotenv()

_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "test-db" / "nba.duckdb")

_shared: dict[str, Any] | None = None


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
    db_path = str(_PROJECT_ROOT / db_path_raw) if not os.path.isabs(db_path_raw) else db_path_raw
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
    logger.info(
        "Schema loaded: %d tables",
        len(schema_by_table),
    )
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


def get_shared() -> dict[str, Any]:
    global _shared
    if _shared is None:
        _shared = build_shared()
    return _shared


_STEP_TRACE_CSS = """
<style>
.step-trace { font-size: 13px; line-height: 1.6; margin-bottom: 8px; }
.step-trace .step { display: flex; gap: 6px; padding: 2px 0; }
.step-trace .step-icon { width: 18px; text-align: center; flex-shrink: 0; }
.step-trace .step-name { font-weight: 600; flex-shrink: 0; min-width: 110px; }
.step-trace .step-summary { color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step-trace .step.complete .step-icon { color: #22c55e; }
.step-trace .step.error .step-icon { color: #ef4444; }
</style>
"""


def _format_step_trace_html(step_logs: list[dict[str, Any]]) -> str:
    if not step_logs:
        return ""
    lines: list[str] = [_STEP_TRACE_CSS, '<div class="step-trace">']
    for i, entry in enumerate(step_logs, 1):
        status = entry.get("status", "complete")
        icon = "✅" if status == "complete" else "❌"
        node = entry.get("node", "?")
        summary = entry.get("summary", "")
        lines.append(
            f'<div class="step {status}">'
            f'<span class="step-icon">{icon}</span>'
            f'<span class="step-name">[{i}] {node}</span>'
            f'<span class="step-summary">{summary}</span>'
            f"</div>"
        )
    lines.append("</div>")
    return "\n".join(lines)


def reset_conversation() -> None:
    global _shared
    _shared = None


def handle_submit(
    message: str, history: list[dict]
) -> Generator[tuple[str, list[dict], str], None, None]:
    shared = get_shared()
    shared["user_message"] = message
    shared["step_logs"] = []
    shared["chat_history"].append({
        "role": "user",
        "content": message,
        "sql": None,
        "error": False,
    })
    history.append({"role": "user", "content": message})

    flow_done = threading.Event()
    flow_exc: list[Exception | None] = [None]

    def run_flow() -> None:
        try:
            chat_flow.run(shared)
        except Exception as e:
            flow_exc[0] = e
        finally:
            flow_done.set()

    thread = threading.Thread(target=run_flow, daemon=True)
    thread.start()

    last_log_count = 0
    while not flow_done.is_set():
        thread.join(timeout=0.3)
        step_logs = shared.get("step_logs", [])
        if len(step_logs) > last_log_count:
            last_log_count = len(step_logs)
            step_html = _format_step_trace_html(step_logs)
            yield "", history, step_html

    if flow_exc[0] is not None:
        logger.error("Flow execution failed: %s", flow_exc[0])
        history.append({
            "role": "assistant",
            "content": f"Sorry, an error occurred: {flow_exc[0]}",
        })
        step_html = _format_step_trace_html(shared.get("step_logs", []))
        yield "", history, step_html
        return

    step_logs = shared.get("step_logs", [])
    history.append({
        "role": "assistant",
        "content": shared.get(
            "response", "Sorry, I couldn't generate a response."
        ),
    })
    step_html = _format_step_trace_html(step_logs)
    yield "", history, step_html


with gr.Blocks(title="NBA Basketball Chatbot") as demo:
    gr.Markdown(
        "# NBA Basketball Chatbot\n"
        "Ask questions about NBA players, teams, games, and statistics "
        "in plain English."
    )

    step_trace = gr.HTML(label="Step Trace", visible=True)
    chatbot = gr.Chatbot(label="Conversation", height=460)
    msg = gr.Textbox(
        label="Your question",
        placeholder="e.g. Who scored the most points per game in the 2023-24 season?",
    )
    clear = gr.ClearButton([msg, chatbot])

    msg.submit(handle_submit, [msg, chatbot], [msg, chatbot, step_trace])

    def _on_clear() -> str:
        reset_conversation()
        return ""

    clear.click(_on_clear, outputs=[step_trace], queue=False)


if __name__ == "__main__":
    demo.launch(
        theme=gr.themes.Soft(),  # pyright: ignore[reportPrivateImportUsage]
    )
