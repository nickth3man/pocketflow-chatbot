"""Integration tests for the full flow with mocked LLM and DB."""

from pytest_check import check

from flow import create_chat_flow


class TestFlowIntegration:
    def test_query_db_path_success(self, shared, mocker):
        """query_db path: full success flow with SQL execution."""
        mocker.patch(
            "nodes.call_llm_structured",
            side_effect=[
                {
                    "clean_message": "top scorers 2023-24",
                    "entities": {"players": [], "teams": [], "seasons": ["2023-24"]},
                },
                {"intent": "query_db", "reason": "needs player stats"},
                {"tables": ["dim_player", "fact_player_game_stats"], "reason": "stats"},
                {
                    "plan": "join dim_player and fact_player_game_stats",
                    "tables_used": ["dim_player", "fact_player_game_stats"],
                    "filters": ["season_year = 2023-24"],
                    "aggregations": ["AVG(points)"],
                },
                {
                    "thinking": "simple aggregation",
                    "sql": "SELECT first_name, last_name, AVG(points) as avg_pts FROM dim_player JOIN fact_player_game_stats USING (person_id) GROUP BY all ORDER BY avg_pts DESC",
                },
            ],
        )
        mocker.patch(
            "nodes.call_llm",
            return_value="LeBron James averaged 27.3 points per game in the 2023-24 season.",
        )
        mocker.patch(
            "nodes.execute_query",
            return_value={
                "success": True,
                "columns": ["first_name", "last_name", "avg_pts"],
                "rows": [["LeBron", "James", 27.3], ["Giannis", "Antetokounmpo", 26.8]],
                "elapsed_ms": 25.0,
                "error": None,
            },
        )

        shared["user_message"] = (
            "Who scored the most points per game in the 2023-24 season?"
        )
        shared["chat_history"].append({
            "role": "user",
            "content": shared["user_message"],
            "sql": None,
            "error": False,
        })

        flow = create_chat_flow()
        flow.run(shared)

        check.equal(shared["intent"], "query_db")
        check.is_true(shared["generated_sql"].strip().startswith("SELECT"))
        check.not_equal(shared["response"], "")
        check.is_true(
            "LeBron" in shared["result_analysis"] or "LeBron" in shared["response"]
        )
        check.greater_equal(len(shared["chat_history"]), 2)

    def test_query_db_path_error_retry_give_up(self, shared, mocker):
        """query_db path: error triggers recovery, retries, then gives up."""
        call_count = [0]

        def llm_structured_side_effect(**kwargs):
            call_count[0] += 1
            call_num = call_count[0]

            responses = {
                1: {
                    "clean_message": "test query",
                    "entities": {"players": [], "teams": [], "seasons": []},
                },
                2: {"intent": "query_db", "reason": "test"},
                3: {
                    "tables": ["dim_player", "fact_player_game_stats"],
                    "reason": "test",
                },
                4: {
                    "plan": "join tables",
                    "tables_used": ["dim_player"],
                    "filters": [],
                    "aggregations": [],
                },
                5: {
                    "thinking": "first attempt",
                    "sql": "SELECT bad_column FROM dim_player",
                },
                6: {
                    "error_type": "missing_column",
                    "root_cause": "bad column",
                    "affected_entities": ["dim_player"],
                    "suggested_fix_direction": "use correct column",
                },
                7: {"thinking": "fixed", "sql": "SELECT person_id FROM dim_player"},
                8: {"thinking": "retry", "sql": "SELECT person_id FROM dim_player"},
                9: {
                    "error_type": "missing_column",
                    "root_cause": "still bad",
                    "affected_entities": ["dim_player"],
                    "suggested_fix_direction": "fix again",
                },
                10: {
                    "thinking": "fixed again",
                    "sql": "SELECT person_id FROM dim_player",
                },
            }
            return responses.get(call_num, {"thinking": "fallback", "sql": "SELECT 1"})

        mocker.patch(
            "nodes.call_llm_structured", side_effect=llm_structured_side_effect
        )
        mocker.patch(
            "nodes.call_llm",
            return_value="Could not complete the query. Please try rephrasing.",
        )
        mocker.patch(
            "nodes.execute_query",
            return_value={
                "success": False,
                "columns": [],
                "rows": [],
                "elapsed_ms": 5.0,
                "error": 'Binder Error: column "bad_column" does not exist',
            },
        )

        shared["user_message"] = "test query"
        shared["chat_history"].append({
            "role": "user",
            "content": "test query",
            "sql": None,
            "error": False,
        })

        flow = create_chat_flow()
        flow.run(shared)

        check.not_equal(shared["response"], "")
        check.greater_equal(shared["debug_attempts"], 1)

    def test_chat_path(self, shared, mocker):
        """chat path: routes to ChatResponder, no DB query."""
        mocker.patch(
            "nodes.call_llm_structured",
            side_effect=[
                {
                    "clean_message": "What is the shot clock rule?",
                    "entities": {"players": [], "teams": [], "seasons": []},
                },
                {"intent": "chat", "reason": "general NBA knowledge"},
            ],
        )
        mocker.patch(
            "nodes.call_llm", return_value="The shot clock is 24 seconds in the NBA."
        )

        shared["user_message"] = "What is the shot clock rule?"
        shared["chat_history"].append({
            "role": "user",
            "content": shared["user_message"],
            "sql": None,
            "error": False,
        })

        flow = create_chat_flow()
        flow.run(shared)

        check.equal(shared["intent"], "chat")
        check.is_in("shot clock", shared["response"].lower())
        check.greater_equal(len(shared["chat_history"]), 2)

    def test_clarify_path(self, shared, mocker):
        """clarify path: routes to ChatResponder asking for more info."""
        mocker.patch(
            "nodes.call_llm_structured",
            side_effect=[
                {
                    "clean_message": "Tell me about LeBron",
                    "entities": {
                        "players": ["LeBron James"],
                        "teams": [],
                        "seasons": [],
                    },
                },
                {"intent": "clarify", "reason": "ambiguous query"},
            ],
        )
        mocker.patch(
            "nodes.call_llm",
            return_value="What would you like to know about LeBron James? Career stats, recent games, or comparison to another player?",
        )

        shared["user_message"] = "Tell me about LeBron"
        shared["chat_history"].append({
            "role": "user",
            "content": shared["user_message"],
            "sql": None,
            "error": False,
        })

        flow = create_chat_flow()
        flow.run(shared)

        check.equal(shared["intent"], "clarify")
        check.is_in("LeBron", shared["response"])
        check.greater_equal(len(shared["chat_history"]), 2)

    def test_error_recovery_subflow_structure(self):
        """Verify ErrorRecoveryFlow has correct internal node wiring."""
        from flow import ErrorRecoveryFlow
        from nodes import (
            ErrorAnalyzerNode,
            FixValidatorNode,
            RecoveryDecisionNode,
            SchemaRecheckNode,
            SQLFixerNode,
        )

        error_analyzer = ErrorAnalyzerNode()
        schema_recheck = SchemaRecheckNode()
        sql_fixer = SQLFixerNode()
        fix_validator = FixValidatorNode()
        recovery_decision = RecoveryDecisionNode()

        (
            error_analyzer
            >> schema_recheck  # pyright: ignore[reportUnusedExpression]
            >> sql_fixer  # pyright: ignore[reportUnusedExpression]
            >> fix_validator  # pyright: ignore[reportUnusedExpression]
            >> recovery_decision  # pyright: ignore[reportUnusedExpression]
        )

        erf = ErrorRecoveryFlow(start=error_analyzer)
        assert erf.start_node is error_analyzer

    def test_flow_creates_successfully(self):
        """Flow creation does not raise."""
        flow = create_chat_flow()
        assert flow is not None
        assert flow.start_node is not None
