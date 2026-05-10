"""Unit tests for utility functions."""

import time
from datetime import datetime

import pytest
from pytest_check import check

from utils.call_llm_structured import (
    _extract_yaml_block,
    _fix_yaml_quoting,
    _rebuild_yaml,
)
from utils.classify_error import classify_error
from utils.format_response_markdown import format_response_markdown
from utils.format_results_table import format_results_table
from utils.format_schema import format_schema
from utils.optimize_sql import optimize_sql
from utils.validate_sql_safety import validate_sql_safety


class TestValidateSqlSafety:
    def test_select_is_safe(self):
        safe, reason = validate_sql_safety("SELECT * FROM dim_player")
        check.is_true(safe)
        check.equal(reason, "SQL is safe")

    def test_drop_is_unsafe(self):
        safe, reason = validate_sql_safety("DROP TABLE dim_player")
        check.is_false(safe)
        check.is_in("SELECT", reason)

    def test_insert_is_unsafe(self):
        safe, _reason = validate_sql_safety("INSERT INTO dim_player VALUES (1)")
        assert not safe

    def test_empty_is_unsafe(self):
        safe, _reason = validate_sql_safety("")
        assert not safe

    def test_select_with_dangerous_keyword_is_unsafe(self):
        safe, reason = validate_sql_safety(
            "SELECT * FROM t UNION SELECT * FROM(SELECT * FROM t) AS sub WHERE EXISTS(SELECT 1 FROM t WHERE false) -- DROP TABLE t"
        )
        check.is_false(safe)
        check.is_in("DROP", reason)

    def test_select_with_multiple_dangerous_keywords(self):
        safe, reason = validate_sql_safety(
            "SELECT 1; CREATE TABLE t (x INT); DROP TABLE t"
        )
        check.is_false(safe)
        check.is_in("CREATE", reason)
        check.is_in("DROP", reason)


class TestClassifyError:
    def test_syntax_error(self):
        assert classify_error("syntax error at or near") == "syntax_error"

    def test_missing_column(self):
        assert classify_error('column "foobar" does not exist') == "missing_column"

    def test_missing_table(self):
        assert classify_error('table "foobar" does not exist') == "missing_table"

    def test_type_mismatch(self):
        assert classify_error("type mismatch: cannot be cast") == "type_mismatch"

    def test_permission_error(self):
        assert classify_error("permission denied") == "permission"

    def test_unknown_error(self):
        assert classify_error("random internal error") == "unknown"

    def test_none_error(self):
        assert classify_error("") == "unknown"


class TestOptimizeSql:
    def test_adds_limit(self):
        result = optimize_sql("SELECT * FROM dim_player")
        assert result.strip().endswith("LIMIT 200;")

    def test_preserves_existing_limit(self):
        result = optimize_sql("SELECT * FROM dim_player LIMIT 5")
        assert "LIMIT 5" in result

    def test_ensures_semicolon(self):
        result = optimize_sql("SELECT 1")
        assert result.strip().endswith(";")


class TestFormatResultsTable:
    def test_basic_table(self):
        table = format_results_table(
            ["Name", "Points"], [["Curry", 30], ["LeBron", 25]]
        )
        check.is_in("| Name | Points |", table)
        check.is_in("| Curry | 30 |", table)
        check.is_in("| LeBron | 25 |", table)

    def test_empty_columns(self):
        assert format_results_table([], []) == ""

    def test_truncation_note(self):
        rows = [[str(i)] for i in range(60)]
        table = format_results_table(["X"], rows, max_display=50)
        assert "Showing 50 of 60 rows." in table

    def test_with_none_values(self):
        table = format_results_table(["A", "B"], [[None, "x"], ["y", None]])
        assert "|  | x |" in table or "| '' | x |" in table
        assert "| y |  |" in table or "| y | '' |" in table


class TestFormatSchema:
    def test_basic_format(self):
        schema = {"dim_player": {"columns": [{"name": "person_id", "type": "BIGINT"}]}}
        result = format_schema(schema)
        assert "TABLE dim_player (person_id BIGINT)" in result


class TestFormatResponseMarkdown:
    def test_full_response(self):
        result = format_response_markdown(
            narrative="Found 12 players.",
            table_md="| Name |\n| --- |\n| Curry |",
            sql="SELECT * FROM dim_player",
            elapsed_ms=42.5,
        )
        check.is_in("Found 12 players.", result)
        check.is_in("View SQL (42ms)", result)
        check.is_in("SELECT * FROM dim_player", result)

    def test_no_sql(self):
        result = format_response_markdown(
            narrative="Hello.", table_md="", sql=None, elapsed_ms=None
        )
        check.is_in("Hello.", result)
        check.is_not_in("View SQL", result)


class TestYamlInternals:
    def test_fix_yaml_quoting_colon_in_value(self):
        fixed = _fix_yaml_quoting("reason: need to: fix this")
        assert '"need to: fix this"' in fixed

    def test_fix_yaml_quoting_already_quoted(self):
        fixed = _fix_yaml_quoting('reason: "already quoted"')
        assert fixed == 'reason: "already quoted"'

    def test_fix_yaml_quoting_hash_in_value(self):
        fixed = _fix_yaml_quoting("sql: SELECT 1 # comment")
        assert '"SELECT 1 # comment"' in fixed

    def test_extract_yaml_block_with_fences_and_extra_text(self):
        result = _extract_yaml_block(
            "Here is the answer:\n```yaml\nkey: value\nfoo: bar\n```\nSome footer text."
        )
        check.is_not_none(result)
        check.is_in("key: value", result)
        check.is_in("foo: bar", result)

    def test_extract_yaml_block_plain_fence(self):
        result = _extract_yaml_block("Some text\n```\na: 1\nb: 2\n```")
        check.is_not_none(result)
        check.is_in("a: 1", result)

    def test_rebuild_yaml_with_required_fields(self):
        text = "thinking: This is a complex: analysis with colons\nsql: SELECT 1\n"
        result = _rebuild_yaml(text, ["thinking", "sql"])
        import yaml

        parsed = yaml.safe_load(result)
        check.is_instance(parsed, dict)
        check.is_in("thinking", parsed)
        check.is_in("sql", parsed)

    def test_rebuild_yaml_no_matching_fields(self):
        result = _rebuild_yaml("just some random text", ["required_field"])
        assert result == "just some random text"


class TestFreezeTimeDemo:
    @pytest.mark.freeze_time("2025-06-01")
    def test_datetime_is_frozen(self):
        assert datetime.now().isoformat().startswith("2025-06-01")

    @pytest.mark.freeze_time("2025-06-01")
    def test_time_is_frozen(self, freezer):
        t1 = time.time()
        freezer.move_to("2025-06-15")
        t2 = time.time()
        assert t2 > t1
