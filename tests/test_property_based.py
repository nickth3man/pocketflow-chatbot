import string

import pytest
from hypothesis import given
from hypothesis import strategies as st

from utils.format_results_table import format_results_table
from utils.optimize_sql import optimize_sql
from utils.validate_sql_safety import validate_sql_safety


@pytest.mark.property
@given(
    st.integers(min_value=1, max_value=1000),
    st.integers(min_value=1, max_value=1000),
)
def test_optimize_sql_adds_exactly_one_limit(default_limit: int, selected: int) -> None:
    result = optimize_sql("SELECT * FROM fact_game", default_limit=default_limit)

    assert result == f"SELECT * FROM fact_game LIMIT {default_limit};"
    assert optimize_sql(f"SELECT * FROM fact_game LIMIT {selected}") == (
        f"SELECT * FROM fact_game LIMIT {selected};"
    )


@pytest.mark.property
@given(st.sampled_from(["DROP", "ALTER", "INSERT", "UPDATE", "DELETE", "ATTACH"]))
def test_validate_sql_safety_rejects_dangerous_keywords(keyword: str) -> None:
    is_safe, reason = validate_sql_safety(f"SELECT * FROM games; {keyword} TABLE games")

    assert not is_safe
    assert keyword in reason.upper()


@pytest.mark.property
@given(
    st.lists(
        st.text(alphabet=string.ascii_letters, min_size=1, max_size=12),
        min_size=1,
        max_size=5,
    ),
    st.lists(
        st.lists(st.one_of(st.none(), st.integers(), st.text(max_size=20)), max_size=5),
        max_size=20,
    ),
)
def test_format_results_table_is_valid_markdown_shape(
    columns: list[str], rows: list[list[object]]
) -> None:
    normalized_rows = [row[: len(columns)] for row in rows if len(row) >= len(columns)]

    result = format_results_table(columns, normalized_rows, max_display=10)

    if not normalized_rows:
        assert result == ""
        return

    lines = result.splitlines()
    assert lines[0].startswith("| ")
    assert lines[1] == "| " + " | ".join("---" for _ in columns) + " |"
    assert len(lines) >= min(len(normalized_rows), 10) + 2
