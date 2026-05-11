"""
Batch evaluation harness — runs 30 test queries and writes a JSON report.
Usage: uv run python run_eval.py
"""

import json
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from typing import Any

QUERY_TIMEOUT_S = 300  # hard ceiling per query — prevents runaway retry loops

from dotenv import load_dotenv

from flow import create_chat_flow
from utils.get_full_schema import get_full_schema
from utils.logging_setup import setup_logging

load_dotenv()
setup_logging(prefix="eval")

_PROJECT_ROOT = Path(__file__).resolve().parent
_DEFAULT_DB_PATH = str(_PROJECT_ROOT / "test-db" / "nba.duckdb")

QUERIES: list[dict[str, Any]] = [
    # ── Team season records (the bug category) ──────────────────────────
    {
        "id": 1,
        "category": "team_record",
        "query": "What was the Warriors record in the 2023-24 season?",
        "checks": ["season_year", "82_game_cap"],
    },
    {
        "id": 2,
        "category": "team_record",
        "query": "How did the Lakers do last season?",
        "checks": ["season_year", "82_game_cap"],
    },
    {
        "id": 3,
        "category": "team_record",
        "query": "Show me the full NBA standings for 2023-24",
        "checks": ["82_game_cap"],
    },
    {
        "id": 4,
        "category": "team_record",
        "query": "What was Boston's win-loss record in 2022-23?",
        "checks": ["season_year", "82_game_cap"],
    },
    {
        "id": 5,
        "category": "team_record",
        "query": "Which team had the best record last season?",
        "checks": ["82_game_cap"],
    },
    # ── Player scoring leaders ───────────────────────────────────────────
    {
        "id": 6,
        "category": "player_stats",
        "query": "Who led the NBA in scoring in 2023-24?",
        "checks": ["season_year", "has_player_name"],
    },
    {
        "id": 7,
        "category": "player_stats",
        "query": "Top 10 scorers this season",
        "checks": ["season_year", "has_player_name"],
    },
    {
        "id": 8,
        "category": "player_stats",
        "query": "Who had the most assists per game in the 2023-24 season?",
        "checks": ["season_year", "has_player_name"],
    },
    {
        "id": 9,
        "category": "player_stats",
        "query": "Best rebounders in the 2022-23 season",
        "checks": ["season_year"],
    },
    {
        "id": 10,
        "category": "player_stats",
        "query": "Which player had the highest true shooting percentage last season (min 50 games)?",
        "checks": ["season_year"],
    },
    # ── Individual player lookups ────────────────────────────────────────
    {
        "id": 11,
        "category": "individual_player",
        "query": "What were Stephen Curry's stats in the 2023-24 season?",
        "checks": ["season_year", "has_curry"],
    },
    {
        "id": 12,
        "category": "individual_player",
        "query": "How many points did LeBron James average last season?",
        "checks": ["season_year"],
    },
    {
        "id": 13,
        "category": "individual_player",
        "query": "Show me Nikola Jokic's stats for 2022-23",
        "checks": ["season_year"],
    },
    {
        "id": 14,
        "category": "individual_player",
        "query": "How many three pointers did Klay Thompson make in 2023-24?",
        "checks": ["season_year"],
    },
    {
        "id": 15,
        "category": "individual_player",
        "query": "What is Joel Embiid's career scoring average?",
        "checks": [],  # multi-season intentional
    },
    # ── Head-to-head comparisons ─────────────────────────────────────────
    {
        "id": 16,
        "category": "comparison",
        "query": "Compare LeBron James and Stephen Curry stats in 2023-24",
        "checks": ["season_year"],
    },
    {
        "id": 17,
        "category": "comparison",
        "query": "Who shot a higher field goal percentage last season: Durant or Giannis?",
        "checks": ["season_year"],
    },
    {
        "id": 18,
        "category": "comparison",
        "query": "Luka vs Jokic assists per game in 2022-23",
        "checks": ["season_year"],
    },
    # ── Multi-season / career queries ────────────────────────────────────
    {
        "id": 19,
        "category": "multi_season",
        "query": "How has Curry's three-point percentage changed over the last 3 seasons?",
        "checks": [],  # multi-season intentional
    },
    {
        "id": 20,
        "category": "multi_season",
        "query": "Which team has the best overall record across the last two seasons?",
        "checks": [],  # multi-season intentional
    },
    # ── Advanced metrics ─────────────────────────────────────────────────
    {
        "id": 21,
        "category": "advanced_stats",
        "query": "Which team had the best net rating in 2023-24?",
        "checks": ["season_year"],
    },
    {
        "id": 22,
        "category": "advanced_stats",
        "query": "Top players by PER equivalent (net rating) last season",
        "checks": ["season_year"],
    },
    {
        "id": 23,
        "category": "advanced_stats",
        "query": "Which Warriors player had the best plus/minus in 2023-24?",
        "checks": ["season_year"],
    },
    # ── Play-by-play ─────────────────────────────────────────────────────
    {
        "id": 24,
        "category": "play_by_play",
        "query": "Who hit the most clutch three pointers (last 2 min of 4th quarter or OT)?",
        "checks": [],
    },
    {
        "id": 25,
        "category": "play_by_play",
        "query": "Most shot attempts in clutch situations last season",
        "checks": [],
    },
    # ── Edge cases / robustness ──────────────────────────────────────────
    {
        "id": 26,
        "category": "edge_case",
        "query": "What were the Warriors stats in the 1990-91 season?",
        "checks": [],  # should handle missing data gracefully
    },
    {
        "id": 27,
        "category": "edge_case",
        "query": "Stats for player John XYZ who does not exist",
        "checks": [],  # should handle no results gracefully
    },
    {
        "id": 28,
        "category": "edge_case",
        "query": "What was the Warriors record?",  # ambiguous — no season
        "checks": ["82_game_cap"],
    },
    # ── Chat / general ───────────────────────────────────────────────────
    {
        "id": 29,
        "category": "chat",
        "query": "Who is the greatest NBA player of all time?",
        "checks": [],  # should route to chat, no SQL
    },
    {
        "id": 30,
        "category": "chat",
        "query": "Explain what true shooting percentage means",
        "checks": [],  # should route to chat, no SQL
    },
]


def build_shared(schema_by_table: dict) -> dict[str, Any]:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    model = os.environ.get("OPENROUTER_MODEL", "")
    db_path_raw = os.environ.get("DUCKDB_PATH", _DEFAULT_DB_PATH)
    db_path = (
        str(_PROJECT_ROOT / db_path_raw)
        if not os.path.isabs(db_path_raw)
        else db_path_raw
    )
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
    flow: Any, shared_base: dict, query: str
) -> dict[str, Any]:
    shared = {**shared_base, "chat_history": []}
    shared["user_message"] = query
    shared["step_logs"] = []
    shared["chat_history"].append({"role": "user", "content": query, "sql": None, "error": False})

    t0 = time.monotonic()
    error = None
    try:
        with ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(flow.run, shared)
            try:
                future.result(timeout=QUERY_TIMEOUT_S)
            except FuturesTimeout:
                error = f"query timed out after {QUERY_TIMEOUT_S}s"
            except Exception as e:
                error = str(e)
    except Exception as e:
        error = str(e)
    elapsed = time.monotonic() - t0

    sql_result = shared.get("sql_result")
    rows = sql_result.get("rows", []) if sql_result else []
    cols = sql_result.get("columns", []) if sql_result else []

    return {
        "sql": shared.get("generated_sql"),
        "response": shared.get("response", ""),
        "intent": shared.get("intent"),
        "rows": rows,
        "columns": cols,
        "step_logs": shared.get("step_logs", []),
        "elapsed_s": round(elapsed, 2),
        "error": error,
    }


def check_result(result: dict, checks: list[str]) -> list[str]:
    """Return list of failed check names."""
    failures = []
    sql = (result.get("sql") or "").upper()
    rows = result.get("rows", [])
    cols = result.get("columns", [])

    if "season_year" in checks and result.get("intent") == "query_db":
        if "SEASON_YEAR" not in sql and sql:
            failures.append("season_year: filter missing from SQL")

    if "82_game_cap" in checks and rows and result.get("intent") == "query_db":
        # find a 'games' or 'count' column and check all values
        game_cols = [c for c in cols if c.lower() in ("games", "count", "game_count", "total_games")]
        for gc in game_cols:
            idx = cols.index(gc)
            for row in rows:
                val = row[idx] if isinstance(row, list) else row.get(gc)
                try:
                    if int(val) > 90:
                        failures.append(f"82_game_cap: {gc}={val} exceeds 90")
                        break
                except (TypeError, ValueError):
                    pass

    if "has_player_name" in checks and rows:
        name_cols = [c for c in cols if "name" in c.lower() or "player" in c.lower()]
        if not name_cols:
            failures.append("has_player_name: no name column in results")

    if "has_curry" in checks and rows:
        flat = str(rows).lower()
        if "curry" not in flat:
            failures.append("has_curry: Curry not found in results")

    return failures


def main() -> None:
    api_key = os.environ.get("OPENROUTER_API_KEY")
    model = os.environ.get("OPENROUTER_MODEL")
    if not api_key or not model:
        print("ERROR: OPENROUTER_API_KEY and OPENROUTER_MODEL must be set in .env")
        sys.exit(1)

    db_path_raw = os.environ.get("DUCKDB_PATH", _DEFAULT_DB_PATH)
    db_path = (
        str(_PROJECT_ROOT / db_path_raw)
        if not os.path.isabs(db_path_raw)
        else db_path_raw
    )
    if not os.path.isfile(db_path):
        print(f"ERROR: Database not found at {db_path}")
        sys.exit(1)

    print(f"Loading schema from {db_path}...")
    schema_by_table = get_full_schema(db_path)
    shared_base = build_shared(schema_by_table)

    results = []
    for q in QUERIES:
        flow = create_chat_flow()
        print(f"[{q['id']:02d}/30] {q['query'][:70]}", end=" ... ", flush=True)
        result = run_query(flow, shared_base, q["query"])
        failures = check_result(result, q.get("checks", []))
        record = {
            "id": q["id"],
            "category": q["category"],
            "query": q["query"],
            "intent": result["intent"],
            "sql": result["sql"],
            "row_count": len(result["rows"]),
            "columns": result["columns"],
            "sample_rows": result["rows"][:3],
            "response_snippet": result["response"][:500],
            "elapsed_s": result["elapsed_s"],
            "step_logs": result["step_logs"],
            "check_failures": failures,
            "flow_error": result["error"],
        }
        results.append(record)
        status = "PASS" if not failures and not result["error"] else "FAIL"
        print(f"{status} ({result['elapsed_s']}s, {len(result['rows'])} rows)")

    out_path = _PROJECT_ROOT / "eval_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nResults written to {out_path}")

    passed = sum(1 for r in results if not r["check_failures"] and not r["flow_error"])
    print(f"\nSummary: {passed}/30 passed automated checks")
    for r in results:
        if r["check_failures"] or r["flow_error"]:
            print(f"  FAIL [{r['id']:02d}] {r['query'][:60]}")
            for f in r["check_failures"]:
                print(f"       - {f}")
            if r["flow_error"]:
                print(f"       - flow error: {r['flow_error']}")


if __name__ == "__main__":
    main()
