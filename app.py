import threading
from collections.abc import Generator
from typing import Any

import gradio as gr
from dotenv import load_dotenv

from flow import chat_flow
from utils.logging_setup import setup_logging
from utils.shared_builder import build_shared

logger = setup_logging(prefix="app")

load_dotenv()

_shared: dict[str, Any] | None = None

_SUGGESTED_QUESTIONS = [
    "Who led the NBA in scoring in 2023-24?",
    "Best 3-point shooters this season",
    "Warriors win/loss record 2023-24",
    "LeBron James career stats by season",
    "Top assist leaders last season",
    "Most blocks per game 2023-24",
    "Compare Luka Doncic vs Jayson Tatum",
    "Teams with best net rating 2023-24",
]

_NBA_CSS = """
/* ── Base & font ────────────────────────────────────────── */
body, .gradio-container {
    background: #0d1b2a !important;
    font-family: 'Inter', 'Segoe UI', system-ui, sans-serif !important;
    color: #e2e8f0 !important;
}
.gradio-container { max-width: 1400px !important; margin: 0 auto !important; }

/* ── Header ─────────────────────────────────────────────── */
#nba-header {
    background: linear-gradient(135deg, #1a2942 0%, #0d1b2a 60%, #1a1a2e 100%);
    border-bottom: 3px solid #f37021;
    padding: 20px 28px 16px;
    border-radius: 12px 12px 0 0;
    margin-bottom: 0;
}
#nba-header h1 {
    font-size: 26px !important;
    font-weight: 800 !important;
    color: #ffffff !important;
    margin: 0 0 4px !important;
    letter-spacing: -0.5px;
}
#nba-header p {
    color: #94a3b8 !important;
    font-size: 14px !important;
    margin: 0 !important;
}
.nba-ball { font-size: 28px; vertical-align: middle; margin-right: 10px; }

/* ── Suggested questions ────────────────────────────────── */
#suggestions-row {
    background: #132040;
    padding: 12px 16px;
    border-bottom: 1px solid #1e3a5f;
    overflow-x: auto;
    white-space: nowrap;
}
.suggestion-btn {
    display: inline-block !important;
    background: #1e3a5f !important;
    color: #93c5fd !important;
    border: 1px solid #2d5a8e !important;
    border-radius: 20px !important;
    padding: 6px 14px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    cursor: pointer !important;
    margin: 3px !important;
    transition: all 0.18s ease !important;
    white-space: nowrap !important;
}
.suggestion-btn:hover {
    background: #f37021 !important;
    color: #ffffff !important;
    border-color: #f37021 !important;
    transform: translateY(-1px) !important;
}

/* ── Main panels ────────────────────────────────────────── */
#chat-col, #sidebar-col {
    background: #132040;
    border-radius: 0;
    padding: 0;
}
#sidebar-col { border-left: 1px solid #1e3a5f; }

/* ── Chatbot ────────────────────────────────────────────── */
#chatbot-panel .chatbot {
    background: #0d1b2a !important;
    border: none !important;
    border-radius: 0 !important;
}
#chatbot-panel .message.user {
    background: #1e3a5f !important;
    color: #e2e8f0 !important;
    border-radius: 18px 18px 4px 18px !important;
}
#chatbot-panel .message.bot {
    background: #1a2942 !important;
    color: #e2e8f0 !important;
    border-radius: 18px 18px 18px 4px !important;
    border-left: 3px solid #f37021 !important;
}
#chatbot-panel .message table {
    border-collapse: collapse !important;
    width: 100% !important;
    font-size: 13px !important;
    margin: 8px 0 !important;
}
#chatbot-panel .message th {
    background: #1e3a5f !important;
    color: #93c5fd !important;
    padding: 8px 12px !important;
    text-align: left !important;
    font-weight: 600 !important;
    border-bottom: 2px solid #f37021 !important;
}
#chatbot-panel .message td {
    padding: 7px 12px !important;
    border-bottom: 1px solid #1e3a5f !important;
    color: #cbd5e1 !important;
}
#chatbot-panel .message tr:hover td { background: #1a2942 !important; }
#chatbot-panel .message details summary {
    color: #64748b !important;
    font-size: 12px !important;
    cursor: pointer !important;
    user-select: none;
}
#chatbot-panel .message details summary:hover { color: #f37021 !important; }
#chatbot-panel .message pre, #chatbot-panel .message code {
    background: #0a1628 !important;
    border: 1px solid #1e3a5f !important;
    border-radius: 6px !important;
    font-size: 12px !important;
    color: #86efac !important;
}

/* ── Input bar ──────────────────────────────────────────── */
#input-row {
    background: #132040;
    padding: 12px 16px;
    border-top: 1px solid #1e3a5f;
}
#msg-box textarea {
    background: #1a2942 !important;
    border: 1px solid #2d5a8e !important;
    border-radius: 10px !important;
    color: #e2e8f0 !important;
    font-size: 15px !important;
    resize: none !important;
}
#msg-box textarea:focus {
    border-color: #f37021 !important;
    outline: none !important;
    box-shadow: 0 0 0 2px rgba(243,112,33,0.2) !important;
}
#msg-box textarea::placeholder { color: #475569 !important; }
#ask-btn {
    background: #f37021 !important;
    color: white !important;
    border: none !important;
    border-radius: 10px !important;
    font-weight: 700 !important;
    font-size: 15px !important;
    padding: 10px 28px !important;
    transition: background 0.18s !important;
}
#ask-btn:hover { background: #e05a0a !important; }
#clear-btn {
    background: transparent !important;
    color: #64748b !important;
    border: 1px solid #2d5a8e !important;
    border-radius: 10px !important;
    font-size: 13px !important;
    transition: all 0.18s !important;
}
#clear-btn:hover {
    color: #ef4444 !important;
    border-color: #ef4444 !important;
}

/* ── Sidebar panels ─────────────────────────────────────── */
.sidebar-section {
    background: #0d1b2a;
    border-radius: 8px;
    margin: 12px;
    padding: 14px;
    border: 1px solid #1e3a5f;
}
.sidebar-title {
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: #64748b;
    margin-bottom: 10px;
    padding-bottom: 6px;
    border-bottom: 1px solid #1e3a5f;
}

/* ── Step trace ─────────────────────────────────────────── */
.step-trace-wrap { font-size: 12.5px; line-height: 1.7; }
.step-row {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    padding: 4px 0;
    border-bottom: 1px solid #0d1b2a;
}
.step-row:last-child { border-bottom: none; }
.step-num {
    background: #1e3a5f;
    color: #93c5fd;
    font-size: 10px;
    font-weight: 700;
    min-width: 20px;
    height: 20px;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    margin-top: 1px;
}
.step-num.err { background: #450a0a; color: #ef4444; }
.step-node {
    font-weight: 600;
    color: #93c5fd;
    font-size: 12px;
    min-width: 120px;
    flex-shrink: 0;
}
.step-node.err { color: #ef4444; }
.step-summary {
    color: #64748b;
    font-size: 12px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    flex: 1;
}
.step-done .step-summary { color: #4ade80; }
.step-err .step-summary { color: #ef4444; }

/* ── Metadata bar ───────────────────────────────────────── */
.meta-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px;
}
.meta-card {
    background: #132040;
    border: 1px solid #1e3a5f;
    border-radius: 6px;
    padding: 8px 10px;
    text-align: center;
}
.meta-value {
    font-size: 20px;
    font-weight: 800;
    color: #f37021;
    line-height: 1.2;
}
.meta-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    color: #64748b;
    margin-top: 2px;
}

/* ── Chart panel ────────────────────────────────────────── */
#chart-panel { min-height: 240px; }
#chart-panel .gradio-plot { border: none !important; background: transparent !important; }

/* ── Empty states ───────────────────────────────────────── */
.empty-state {
    color: #334155;
    font-size: 13px;
    text-align: center;
    padding: 20px 0;
    font-style: italic;
}

/* ── Scrollbars ─────────────────────────────────────────── */
::-webkit-scrollbar { width: 6px; height: 6px; }
::-webkit-scrollbar-track { background: #0d1b2a; }
::-webkit-scrollbar-thumb { background: #1e3a5f; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #2d5a8e; }
"""


def get_shared() -> dict[str, Any]:
    global _shared
    if _shared is None:
        _shared = build_shared()
    return _shared


def reset_conversation() -> None:
    global _shared
    _shared = None


# ── Chart generation ────────────────────────────────────────────────────────


def _try_generate_chart(sql_result: dict[str, Any] | None):  # type: ignore[return]
    """Return a matplotlib Figure if the result set is chart-able, else None."""
    try:
        import matplotlib  # type: ignore[import-untyped]

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore[import-untyped]
    except ImportError:
        return None

    if not sql_result or not sql_result.get("success"):
        return None

    columns: list[str] = sql_result.get("columns", [])
    rows: list[list[Any]] = sql_result.get("rows", [])

    if not rows or len(columns) < 2 or len(rows) < 2:
        return None

    # Find label column (first string-ish column) and value columns (numeric)
    import numbers

    label_col_idx: int | None = None
    value_col_idxs: list[int] = []

    sample_row = rows[0]
    for i, val in enumerate(sample_row):
        if label_col_idx is None and isinstance(val, str):
            label_col_idx = i
        elif isinstance(val, numbers.Number) and not isinstance(val, bool):
            value_col_idxs.append(i)

    if label_col_idx is None or not value_col_idxs:
        return None

    # Cap at 20 rows for readability
    display_rows = rows[:20]
    labels = [str(r[label_col_idx]) for r in display_rows]
    primary_val_idx = value_col_idxs[0]
    values = []
    for r in display_rows:
        v = r[primary_val_idx]
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            return None

    col_label = columns[primary_val_idx]

    # Choose horizontal bar for ranked lists (many labels), vertical for few
    horizontal = len(labels) > 6

    fig, ax = plt.subplots(
        figsize=(7, max(3, len(labels) * 0.38)) if horizontal else (7, 4),
        facecolor="#0d1b2a",
    )
    ax.set_facecolor("#0d1b2a")

    orange = "#f37021"
    bar_colors = [orange if i == 0 else "#1e3a5f" for i in range(len(labels))]

    if horizontal:
        labels_rev = labels[::-1]
        values_rev = values[::-1]
        bar_colors_rev = bar_colors[::-1]
        bars = ax.barh(
            labels_rev, values_rev, color=bar_colors_rev, height=0.65, edgecolor="none"
        )
        ax.set_xlabel(col_label, color="#94a3b8", fontsize=11)
        # Value labels on bars
        for bar, val in zip(bars, values_rev, strict=False):
            ax.text(
                bar.get_width() + max(values) * 0.01,
                bar.get_y() + bar.get_height() / 2,
                f"{val:,.1f}" if val != int(val) else f"{int(val):,}",
                va="center",
                ha="left",
                fontsize=9,
                color="#94a3b8",
            )
        ax.set_xlim(0, max(values) * 1.18)
    else:
        bars = ax.bar(
            range(len(labels)), values, color=bar_colors, width=0.6, edgecolor="none"
        )
        ax.set_xticks(range(len(labels)))
        ax.set_xticklabels(
            labels, rotation=20, ha="right", fontsize=10, color="#94a3b8"
        )
        ax.set_ylabel(col_label, color="#94a3b8", fontsize=11)
        for bar, val in zip(bars, values, strict=False):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + max(values) * 0.01,
                f"{val:,.1f}" if val != int(val) else f"{int(val):,}",
                ha="center",
                va="bottom",
                fontsize=9,
                color="#94a3b8",
            )
        ax.set_ylim(0, max(values) * 1.18)

    # Styling
    ax.tick_params(colors="#94a3b8", labelsize=10)
    for spine in ax.spines.values():
        spine.set_edgecolor("#1e3a5f")
    ax.tick_params(axis="x" if horizontal else "y", colors="#1e3a5f", length=0)
    ax.grid(axis="x" if horizontal else "y", color="#1e3a5f", linewidth=0.5, alpha=0.7)
    ax.set_title(col_label, color="#e2e8f0", fontsize=13, fontweight="bold", pad=10)

    fig.tight_layout(pad=1.2)
    return fig


# ── Step trace HTML ──────────────────────────────────────────────────────────


def _format_step_trace_html(step_logs: list[dict[str, Any]]) -> str:
    if not step_logs:
        return '<div class="empty-state">Waiting for query...</div>'

    rows: list[str] = ['<div class="step-trace-wrap">']
    for i, entry in enumerate(step_logs, 1):
        status = entry.get("status", "complete")
        is_err = status == "error"
        num_cls = "err" if is_err else ""
        node_cls = "err" if is_err else ""
        row_cls = "step-err" if is_err else "step-done"
        summary = entry.get("summary", "")
        node = entry.get("node", "?")
        icon = "✕" if is_err else str(i)
        rows.append(
            f'<div class="step-row {row_cls}">'
            f'<div class="step-num {num_cls}">{icon}</div>'
            f'<div class="step-node {node_cls}">{node}</div>'
            f'<div class="step-summary">{summary}</div>'
            f"</div>"
        )
    rows.append("</div>")
    return "\n".join(rows)


# ── Query metadata HTML ──────────────────────────────────────────────────────


def _format_metadata_html(shared: dict[str, Any]) -> str:
    sql_result = shared.get("sql_result")
    if not sql_result or not sql_result.get("success"):
        return '<div class="empty-state">No query run yet</div>'

    row_count = len(sql_result.get("rows", []))
    elapsed = sql_result.get("elapsed_ms", 0)
    tables = shared.get("selected_tables", [])

    elapsed_str = f"{elapsed:.0f}ms" if elapsed < 1000 else f"{elapsed / 1000:.1f}s"

    return f"""
<div class="meta-grid">
  <div class="meta-card">
    <div class="meta-value">{row_count:,}</div>
    <div class="meta-label">Rows Returned</div>
  </div>
  <div class="meta-card">
    <div class="meta-value">{elapsed_str}</div>
    <div class="meta-label">Query Time</div>
  </div>
  <div class="meta-card" style="grid-column: span 2;">
    <div class="meta-value" style="font-size:13px; color:#93c5fd;">{", ".join(tables) or "—"}</div>
    <div class="meta-label">Tables Used</div>
  </div>
</div>
"""


# ── Main submit handler ──────────────────────────────────────────────────────


def handle_submit(
    message: str, history: list[dict]
) -> Generator[tuple[str, list[dict], str, str, Any], None, None]:
    shared = get_shared()
    shared["user_message"] = message
    shared["step_logs"] = []
    shared["sql_result"] = None
    shared["selected_tables"] = []
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
            yield "", history, step_html, "", None

    if flow_exc[0] is not None:
        logger.error("Flow execution failed: %s", flow_exc[0])
        history.append({
            "role": "assistant",
            "content": f"Sorry, an error occurred: {flow_exc[0]}",
        })
        step_html = _format_step_trace_html(shared.get("step_logs", []))
        yield "", history, step_html, "", None
        return

    step_logs = shared.get("step_logs", [])
    response = shared.get("response", "Sorry, I couldn't generate a response.")
    history.append({"role": "assistant", "content": response})

    step_html = _format_step_trace_html(step_logs)
    meta_html = _format_metadata_html(shared)
    chart_fig = _try_generate_chart(shared.get("sql_result"))

    yield "", history, step_html, meta_html, chart_fig


def fill_suggestion(question: str, history: list[dict]) -> tuple[str, list[dict]]:
    return question, history


# ── Gradio UI ────────────────────────────────────────────────────────────────

with gr.Blocks(
    title="NBA Basketball Chatbot",
) as demo:
    # ── Header ──────────────────────────────────────────────
    gr.HTML("""
    <div id="nba-header">
      <h1><span class="nba-ball">🏀</span>NBA Basketball Chatbot</h1>
      <p>Ask anything about players, teams, games, and statistics — powered by real NBA data</p>
    </div>
    """)

    # ── Suggested questions ──────────────────────────────────
    with gr.Row(elem_id="suggestions-row"):
        suggestion_btns = []
        for q in _SUGGESTED_QUESTIONS:
            btn = gr.Button(q, elem_classes=["suggestion-btn"], size="sm")
            suggestion_btns.append(btn)

    # ── Main layout ──────────────────────────────────────────
    with gr.Row():
        # Left: chat panel
        with gr.Column(scale=7, elem_id="chat-col"):
            with gr.Group(elem_id="chatbot-panel"):
                chatbot = gr.Chatbot(
                    label="",
                    height=520,
                    show_label=False,
                    avatar_images=(None, None),
                    render_markdown=True,
                    placeholder="<div style='color:#334155;text-align:center;padding:60px 20px;'><div style='font-size:48px;margin-bottom:12px;'>🏀</div><div style='font-size:16px;font-weight:600;'>Ask about NBA stats, players, or teams</div><div style='font-size:13px;margin-top:8px;'>Click a suggestion above or type your question below</div></div>",
                )

            with gr.Row(elem_id="input-row"):
                msg = gr.Textbox(
                    label="",
                    placeholder="e.g. Who scored the most points per game in 2023-24?",
                    show_label=False,
                    lines=1,
                    max_lines=4,
                    scale=8,
                    elem_id="msg-box",
                )
                ask_btn = gr.Button(
                    "Ask", variant="primary", scale=1, elem_id="ask-btn"
                )
                clear_btn = gr.Button("Clear", scale=1, elem_id="clear-btn")

        # Right: sidebar
        with gr.Column(scale=3, elem_id="sidebar-col"):
            # Query metadata
            gr.HTML(
                '<div class="sidebar-section"><div class="sidebar-title">📊 Query Stats</div>'
            )
            meta_display = gr.HTML(
                '<div class="empty-state">Run a query to see stats</div>'
            )
            gr.HTML("</div>")

            # Step trace
            gr.HTML(
                '<div class="sidebar-section"><div class="sidebar-title">⚙️ Processing Steps</div>'
            )
            step_trace = gr.HTML(
                '<div class="empty-state">Steps will appear here</div>'
            )
            gr.HTML("</div>")

            # Chart
            gr.HTML(
                '<div class="sidebar-section" id="chart-panel"><div class="sidebar-title">📈 Visualization</div>'
            )
            chart_output = gr.Plot(
                label="",
                show_label=False,
                visible=True,
            )
            gr.HTML("</div>")

    # ── Event wiring ─────────────────────────────────────────
    outputs = [msg, chatbot, step_trace, meta_display, chart_output]

    msg.submit(handle_submit, [msg, chatbot], outputs)
    ask_btn.click(handle_submit, [msg, chatbot], outputs)

    def _on_clear() -> tuple[str, str, str, None]:
        reset_conversation()
        return "", "", '<div class="empty-state">Steps will appear here</div>', None

    clear_btn.click(
        _on_clear, outputs=[msg, step_trace, meta_display, chart_output], queue=False
    )

    # Wire suggestion buttons (default-arg captures q at definition time)
    for _q, s_btn in zip(_SUGGESTED_QUESTIONS, suggestion_btns, strict=False):
        s_btn.click(
            fn=lambda captured=_q: captured,
            outputs=[msg],
            queue=False,
        )


if __name__ == "__main__":
    demo.launch(
        css=_NBA_CSS,
        theme=gr.themes.Base(  # pyright: ignore[reportPrivateImportUsage]
            primary_hue="orange",
            neutral_hue="slate",
        ),
    )
