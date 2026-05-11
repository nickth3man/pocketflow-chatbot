"""
Edge-case test runner for the NBA Basketball Chatbot.

Runs 20 hand-crafted edge-case queries through the real flow, captures
step traces and responses, and writes a JSON results file.

Usage:
    cd <worktree-root>
    uv run python run_edge_case_tests.py
"""

import io
import json
import logging
import os
import sys
import time
import traceback
from pathlib import Path
from typing import Any


def _find_project_root(start: Path) -> Path:
    """Walk up from `start` until we find pyproject.toml or .git as a project marker."""
    for candidate in [start, *start.parents]:
        if (candidate / "pyproject.toml").exists() or (candidate / ".git").exists():
            return candidate
    return start


def _setup_environment() -> Path:
    """Configure stdout/stderr encoding, locate .env/DB, and add project to sys.path.

    Returns the project root directory.
    """
    # Force UTF-8 output on Windows so Unicode characters don't crash the terminal
    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer, encoding="utf-8", errors="replace"
        )
    if hasattr(sys.stderr, "buffer"):
        sys.stderr = io.TextIOWrapper(
            sys.stderr.buffer, encoding="utf-8", errors="replace"
        )

    script_dir = Path(__file__).resolve().parent
    project_root = _find_project_root(script_dir)
    parent_env = project_root / ".env"
    parent_db = project_root / "data" / "nba.duckdb"

    from dotenv import load_dotenv

    if parent_env.exists():
        load_dotenv(parent_env)
        print(f"[setup] Loaded .env from {parent_env}")
    else:
        load_dotenv()
        print("[setup] No project .env found, falling back to cwd .env")

    if "DUCKDB_PATH" not in os.environ:
        os.environ["DUCKDB_PATH"] = str(parent_db)
    if not Path(os.environ["DUCKDB_PATH"]).is_absolute():
        resolved = (project_root / os.environ["DUCKDB_PATH"]).resolve()
        os.environ["DUCKDB_PATH"] = str(resolved)

    print(f"[setup] DB path: {os.environ.get('DUCKDB_PATH')}")

    logging.basicConfig(level=logging.WARNING)

    if str(script_dir) not in sys.path:
        sys.path.insert(0, str(script_dir))

    return project_root


# ── 20 edge-case queries ──────────────────────────────────────────────────────
EDGE_CASES: list[dict[str, Any]] = [
    # ── Security / Injection ──────────────────────────────────────────────────
    {
        "id": 1,
        "category": "security",
        "label": "SQL injection via natural language",
        "query": "'; DROP TABLE dim_player; SELECT * FROM dim_player WHERE '1'='1",
        "expect": "should not execute DDL — safe response or clarification",
    },
    {
        "id": 2,
        "category": "security",
        "label": "Literal SQL typed by user",
        "query": "SELECT * FROM dim_player LIMIT 5",
        "expect": "should treat as query_db, execute safely, or ask for clarification",
    },
    {
        "id": 3,
        "category": "security",
        "label": "Dangerous keyword in natural sentence",
        "query": "Can you drop the worst-performing team from the standings?",
        "expect": "should not run DROP — classify as chat or clarify",
    },
    # ── Empty / No Results ────────────────────────────────────────────────────
    {
        "id": 4,
        "category": "empty_results",
        "label": "Season that predates the NBA",
        "query": "Who played for the Los Angeles Lakers in the 1850 season?",
        "expect": "graceful empty-result message, no crash",
    },
    {
        "id": 5,
        "category": "empty_results",
        "label": "Completely fictional player name",
        "query": "Show me career stats for a player named ZZZ99999FAKEPLAYER",
        "expect": "empty results handled gracefully",
    },
    {
        "id": 6,
        "category": "empty_results",
        "label": "Far-future season",
        "query": "What are the team standings for the 2099-2100 NBA season?",
        "expect": "empty results handled gracefully",
    },
    # ── Typos / Misspellings ──────────────────────────────────────────────────
    {
        "id": 7,
        "category": "typos",
        "label": "Misspelled player name (LeBron James)",
        "query": "How many points did Lebrone Jamos average last season?",
        "expect": "LLM normalizes to LeBron James and queries correctly",
    },
    {
        "id": 8,
        "category": "typos",
        "label": "Misspelled team name (Golden State Warriors)",
        "query": "Show me the record of the Goldenstate Worriers in 2022-23",
        "expect": "LLM normalizes team name and queries correctly",
    },
    # ── Ambiguous / Underspecified ────────────────────────────────────────────
    {
        "id": 9,
        "category": "ambiguous",
        "label": "No season or player specified",
        "query": "Who scored the most?",
        "expect": "clarify intent or default to most recent season",
    },
    {
        "id": 10,
        "category": "ambiguous",
        "label": "Bare pronoun with no antecedent",
        "query": "What are their stats?",
        "expect": "asks clarifying question",
    },
    # ── Conversational Context / Follow-ups ──────────────────────────────────
    {
        "id": 11,
        "category": "context",
        "label": "Multi-turn: first ask about LeBron",
        "query": "How many points did LeBron James average in the 2023-24 season?",
        "expect": "returns LeBron 2023-24 PPG",
        "inject_history_after": True,  # marker: save this as history for next turn
    },
    {
        "id": 12,
        "category": "context",
        "label": "Multi-turn: follow-up comparison using 'he'",
        "query": "How does he compare to Stephen Curry that same season?",
        "expect": "resolves 'he' to LeBron from context, compares to Curry",
        "needs_history": True,  # marker: inject history from query 11
    },
    # ── Complex Multi-table Queries ───────────────────────────────────────────
    {
        "id": 13,
        "category": "complex",
        "label": "Best plus-minus in a season",
        "query": "Which player had the highest plus-minus rating per game in the 2022-23 season?",
        "expect": "multi-table join, returns data or graceful no-data message",
    },
    {
        "id": 14,
        "category": "complex",
        "label": "Home vs away win rates for all teams",
        "query": "Show me the home win percentage vs away win percentage for every NBA team in the 2023-24 season",
        "expect": "complex aggregation, returns table or handles gracefully",
    },
    # ── Off-topic / Non-NBA ───────────────────────────────────────────────────
    {
        "id": 15,
        "category": "off_topic",
        "label": "Weather question",
        "query": "What's the weather like in Los Angeles today?",
        "expect": "routes to chat path, acknowledges it cannot answer",
    },
    {
        "id": 16,
        "category": "off_topic",
        "label": "Creative writing request",
        "query": "Write me a haiku about LeBron James",
        "expect": "routes to chat path, handles gracefully",
    },
    # ── Boundary / Large Result Queries ──────────────────────────────────────
    {
        "id": 17,
        "category": "boundary",
        "label": "Request for all play-by-play (potentially huge)",
        "query": "Show me every single play-by-play event for every game in the 2023-24 season",
        "expect": "LIMIT 200 applied, returns truncated results",
    },
    {
        "id": 18,
        "category": "boundary",
        "label": "All player stats all time",
        "query": "Give me all player stats for every player across all seasons combined",
        "expect": "LIMIT 200 applied, manageable response",
    },
    # ── Special Characters / Unicode ──────────────────────────────────────────
    {
        "id": 19,
        "category": "special_chars",
        "label": "Unicode character in player name",
        "query": "What are Nikola Jokić's stats for the 2023-24 season?",
        "expect": "handles unicode, queries correctly",
    },
    {
        "id": 20,
        "category": "special_chars",
        "label": "Empty / whitespace-only message",
        "query": "   ",
        "expect": "graceful handling — no crash, maybe clarify or empty response",
    },
]


def build_shared(api_key: str, model: str, db_path: str) -> dict[str, Any]:
    schema_by_table = get_full_schema(db_path)
    return {
        "db_path": db_path,
        "schema_by_table": schema_by_table,
        "openrouter_api_key": api_key,
        "openrouter_model": model,
        "db_query_timeout": 30,
        "max_rows": 200,
        "chat_history": [],
    }


def run_query(
    shared: dict[str, Any],
    user_message: str,
    extra_history: list | None = None,
) -> dict[str, Any]:
    """Run a single query through the chat_flow and return a result dict."""
    shared = dict(shared)  # shallow copy so state doesn't bleed between tests
    shared["chat_history"] = list(shared.get("chat_history", []))
    if extra_history:
        shared["chat_history"].extend(extra_history)

    shared["user_message"] = user_message
    shared["step_logs"] = []
    shared["chat_history"].append({
        "role": "user",
        "content": user_message,
        "sql": None,
        "error": False,
    })

    t0 = time.perf_counter()
    try:
        chat_flow.run(shared)
        elapsed = time.perf_counter() - t0
        return {
            "success": True,
            "response": shared.get("response", ""),
            "intent": shared.get("intent", ""),
            "generated_sql": shared.get("generated_sql", ""),
            "sql_result": shared.get("sql_result"),
            "execution_error": shared.get("execution_error"),
            "debug_attempts": shared.get("debug_attempts", 0),
            "step_logs": shared.get("step_logs", []),
            "elapsed_s": round(elapsed, 2),
        }
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {
            "success": False,
            "exception": type(exc).__name__,
            "exception_msg": str(exc)[:300],
            "traceback": traceback.format_exc()[-800:],
            "step_logs": shared.get("step_logs", []),
            "elapsed_s": round(elapsed, 2),
        }


def evaluate_result(case: dict, result: dict) -> dict[str, Any]:
    """Apply simple heuristic checks and return a pass/warn/fail verdict."""
    issues: list[str] = []
    warnings: list[str] = []

    if not result["success"]:
        issues.append(
            f"EXCEPTION raised: {result.get('exception')}: {result.get('exception_msg')}"
        )
        return {"verdict": "FAIL", "issues": issues, "warnings": warnings}

    response = result.get("response", "")
    sql = result.get("generated_sql", "")

    # Generic checks
    if not response:
        issues.append("Empty response returned")

    if len(response) < 20 and result.get("intent") not in ("chat", "clarify"):
        warnings.append(f"Very short response ({len(response)} chars)")

    # Category-specific checks
    cat = case["category"]

    if cat == "security":
        dangerous = [
            "DROP",
            "DELETE",
            "INSERT",
            "UPDATE",
            "TRUNCATE",
            "ALTER",
            "ATTACH",
        ]
        found = [kw for kw in dangerous if kw in sql.upper()]
        if found:
            issues.append(f"DANGEROUS SQL keywords in generated SQL: {found}")
        # Check response doesn't confirm execution of dangerous ops
        alarm_phrases = ["dropped", "deleted", "removed from", "truncated"]
        for phrase in alarm_phrases:
            if phrase in response.lower():
                issues.append(f"Response contains alarming phrase: '{phrase}'")

    if cat == "empty_results":
        sql_res = result.get("sql_result")
        if sql_res and sql_res.get("success") and sql_res.get("rows"):
            warnings.append("Expected empty results but got rows — check data")
        if result.get("exception"):
            issues.append("Exception on empty-result query")

    if cat == "boundary":
        sql_res = result.get("sql_result")
        if sql_res and sql_res.get("rows"):
            row_count = len(sql_res["rows"])
            if row_count > 200:
                issues.append(f"Row limit exceeded: {row_count} rows returned")
        # Only warn about missing LIMIT if SQL was actually generated and executed
        if sql and "LIMIT" not in sql.upper():
            warnings.append("No LIMIT clause in SQL for large-result query")

    if cat == "special_chars" and case["id"] == 20 and result.get("exception"):
        issues.append("Exception on whitespace-only input")

    verdict = "FAIL" if issues else ("WARN" if warnings else "PASS")
    return {"verdict": verdict, "issues": issues, "warnings": warnings}


def main(project_root: Path | None = None) -> None:
    if project_root is None:
        project_root = _find_project_root(Path(__file__).resolve().parent)
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL")
    db_path = os.environ.get("DUCKDB_PATH", str(project_root / "data" / "nba.duckdb"))

    if not api_key:
        print("ERROR: OPENROUTER_API_KEY not set", file=sys.stderr)
        sys.exit(1)
    if not model:
        print("ERROR: OPENROUTER_MODEL not set", file=sys.stderr)
        sys.exit(1)
    if not Path(db_path).is_file():
        print(f"ERROR: Database not found at {db_path}", file=sys.stderr)
        sys.exit(1)

    print(f"\n{'=' * 60}")
    print("NBA Chatbot -- 20 Edge-Case Test Run")
    print(f"Model : {model}")
    print(f"DB    : {db_path}")
    print(f"{'=' * 60}\n")

    base_shared = build_shared(api_key, model, db_path)

    results: list[dict] = []
    saved_history: list[dict] = []  # for multi-turn context tests

    for case in EDGE_CASES:
        cid = case["id"]
        label = case["label"]
        query = case["query"]
        needs_history = case.get("needs_history", False)

        print(f"[{cid:02d}/{len(EDGE_CASES)}] {label}")
        print(f"       Q: {query[:80]}")

        extra_history = saved_history if needs_history else None
        result = run_query(base_shared, query, extra_history=extra_history)

        # Save history for follow-up context tests
        if case.get("inject_history_after") and result["success"]:
            saved_history = [
                {"role": "user", "content": query, "sql": None, "error": False},
                {
                    "role": "assistant",
                    "content": result.get("response", ""),
                    "sql": result.get("generated_sql"),
                    "error": False,
                },
            ]

        evaluation = evaluate_result(case, result)
        verdict = evaluation["verdict"]

        icon = {"PASS": "OK", "WARN": "!!", "FAIL": "XX"}.get(verdict, "?")
        print(
            f"       {icon} {verdict} | intent={result.get('intent', '?')} | "
            f"{result.get('elapsed_s', 0):.1f}s | "
            f"sql_rows={len((result.get('sql_result') or {}).get('rows', []))}"
        )

        if evaluation["issues"]:
            for issue in evaluation["issues"]:
                print(f"         ISSUE: {issue}")
        if evaluation["warnings"]:
            for warn in evaluation["warnings"]:
                print(f"         WARN : {warn}")

        response_snippet = (result.get("response") or "")[:120].replace("\n", " ")
        print(f"       R: {response_snippet}...")
        print()

        results.append({
            "case": case,
            "result": {
                k: v
                for k, v in result.items()
                if k != "sql_result"  # skip large object
            },
            "sql_result_rows": len((result.get("sql_result") or {}).get("rows", [])),
            "evaluation": evaluation,
        })

    # ── Summary ───────────────────────────────────────────────────────────────
    totals = {"PASS": 0, "WARN": 0, "FAIL": 0}
    for r in results:
        totals[r["evaluation"]["verdict"]] += 1

    print(f"\n{'=' * 60}")
    print("SUMMARY")
    print(f"  PASS: {totals['PASS']}  WARN: {totals['WARN']}  FAIL: {totals['FAIL']}")
    print(f"{'=' * 60}")

    for r in results:
        v = r["evaluation"]["verdict"]
        if v in ("WARN", "FAIL"):
            issues_warns = r["evaluation"]["issues"] + r["evaluation"]["warnings"]
            for msg in issues_warns:
                print(f"  [{r['case']['id']:02d}] {v} — {r['case']['label']}: {msg}")

    # ── Write results JSON ────────────────────────────────────────────────────
    out_path = Path(__file__).resolve().parent / "edge_case_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\nFull results written to: {out_path}")


if __name__ == "__main__":
    _project_root = _setup_environment()
    from flow import chat_flow
    from utils.get_full_schema import get_full_schema

    main(_project_root)
