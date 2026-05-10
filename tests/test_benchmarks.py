import pytest

from utils.format_results_table import format_results_table
from utils.optimize_sql import optimize_sql


@pytest.mark.benchmark
def test_format_results_table_benchmark(benchmark) -> None:
    rows = [[f"Player {index}", index, index % 12] for index in range(200)]

    result = benchmark(format_results_table, ["player", "points", "assists"], rows)

    assert result.startswith("| player | points | assists |")


@pytest.mark.benchmark
def test_optimize_sql_benchmark(benchmark) -> None:
    result = benchmark(optimize_sql, "SELECT * FROM fact_player_game_stats")

    assert result == "SELECT * FROM fact_player_game_stats LIMIT 200;"
