"""Tests for execute_query module."""

import duckdb
import pytest

from utils.execute_query import _run_query, execute_query


class TestRunQuery:
    def test_run_query_success(self, mocker):
        mock_con = mocker.MagicMock()
        mock_con.execute.return_value.description = [["col1"]]
        mock_con.execute.return_value.fetchmany.return_value = [[1]]
        mocker.patch("duckdb.connect", return_value=mock_con)
        columns, rows, elapsed_ms = _run_query(":memory:", "SELECT 1", 200)
        assert columns == ["col1"]
        assert rows == [[1]]
        assert elapsed_ms >= 0

    def test_run_query_sets_memory_limit(self, mocker):
        mock_con = mocker.MagicMock()
        mock_con.execute.return_value.description = [["x"]]
        mock_con.execute.return_value.fetchmany.return_value = [["y"]]
        mocker.patch("duckdb.connect", return_value=mock_con)
        _run_query(":memory:", "SELECT 'y'", 200)
        mock_con.execute.assert_any_call("SET memory_limit = '2GB'")

    def test_run_query_closes_connection(self, mocker):
        mock_con = mocker.MagicMock()
        mock_con.execute.return_value.description = [["x"]]
        mock_con.execute.return_value.fetchmany.return_value = [["y"]]
        mocker.patch("duckdb.connect", return_value=mock_con)
        _run_query(":memory:", "SELECT 'y'", 200)
        mock_con.close.assert_called_once()

    def test_run_query_respects_max_rows(self, mocker):
        mock_con = mocker.MagicMock()
        mock_con.execute.return_value.description = [["x"]]
        mocker.patch("duckdb.connect", return_value=mock_con)
        _run_query(":memory:", "SELECT 1", max_rows=10)
        mock_con.execute.return_value.fetchmany.assert_called_with(10)


class TestExecuteQuery:
    def test_execute_query_success(self, mocker):
        mocker.patch(
            "utils.execute_query._run_query",
            return_value=(["col1"], [[1]], 5.0),
        )
        result = execute_query(":memory:", "SELECT 1", max_rows=200, timeout_seconds=30)
        assert result["success"] is True
        assert result["columns"] == ["col1"]
        assert result["rows"] == [[1]]

    def test_execute_query_timeout(self, mocker):
        mocker.patch("utils.execute_query._run_query", side_effect=TimeoutError)
        result = execute_query(":memory:", "SELECT 1", max_rows=5, timeout_seconds=0)
        assert result["success"] is False
        assert "timed out" in result["error"].lower()

    def test_execute_query_duckdb_error(self, mocker):
        mocker.patch(
            "utils.execute_query._run_query", side_effect=duckdb.Error("catalog error")
        )
        result = execute_query(
            ":memory:", "SELECT bad", max_rows=200, timeout_seconds=30
        )
        assert result["success"] is False
        assert "catalog error" in result["error"]

    def test_execute_query_unknown_error_propagates(self, mocker):
        mocker.patch(
            "utils.execute_query._run_query", side_effect=RuntimeError("unknown error")
        )
        with pytest.raises(RuntimeError, match="unknown error"):
            execute_query(":memory:", "SELECT bad", max_rows=200, timeout_seconds=30)
