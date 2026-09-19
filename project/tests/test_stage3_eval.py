import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch
from agent.nodes import (
    create_plan,
    validate_plan,
    resolve_project,
    validate_tool_result,
    evaluate_goal,
    MAX_TRANSIENT_RETRIES,
    MAX_AGENT_STEPS,
)


class TestStage3ContinuousEvaluation(unittest.TestCase):
    def test_create_and_validate_plan_read(self):
        state = {
            "intent": "read",
            "selected_tool": "read_project_data",
            "project_name": "Metro Line Extension",
            "tool_arguments": {"record_type": "expense"},
        }
        state = create_plan(state)
        self.assertEqual(len(state["plan"]), 4)
        self.assertEqual(state["plan"][0]["action"], "resolve_project")

        state = validate_plan(state)
        self.assertTrue(state["plan_valid"])

    def test_validate_plan_unsupported_operation(self):
        state = {
            "intent": "unsupported",
            "selected_tool": "delete_project",
            "incoming_message": "Delete Metro Line Extension",
        }
        state = create_plan(state)
        state = validate_plan(state)
        self.assertFalse(state["plan_valid"])
        self.assertIn("not supported", state["final_response"].lower())

    def test_resolve_project_ambiguous_does_not_guess(self):
        # Multiple projects returned by query
        mock_rows = [
            {"id": "p1", "project_name": "Metro Line Extension", "project_code": "MLE-01"},
            {"id": "p2", "project_name": "Metro Line North", "project_code": "MLN-02"},
        ]
        with patch("agent.nodes.execute_query", return_value=mock_rows):
            state = {"project_name": "Metro"}
            state = resolve_project(state)
            self.assertIsNone(state["project_id"])
            self.assertEqual(state["resolution_status"], "ambiguous")
            self.assertIn("Which project did you mean?", state["final_response"])

    def test_resolve_project_not_found_asks_user(self):
        with patch("agent.nodes.execute_query", return_value=[]):
            state = {"project_name": "NonExistentProject"}
            state = resolve_project(state)
            self.assertIsNone(state["project_id"])
            self.assertEqual(state["resolution_status"], "not_found")
            self.assertIn("Could not find any project", state["final_response"])

    def test_validate_tool_result_retry_bounded(self):
        state = {
            "tool_result": {"status": "error", "error": "Connection timed out"},
            "retry_count": 0,
        }
        # First retry attempt
        state = validate_tool_result(state)
        self.assertEqual(state["validation_status"], "retry")
        self.assertEqual(state["retry_count"], 1)

        # Second retry attempt
        state = validate_tool_result(state)
        self.assertEqual(state["validation_status"], "retry")
        self.assertEqual(state["retry_count"], 2)

        # Exceeded max retries
        state = validate_tool_result(state)
        self.assertEqual(state["validation_status"], "failed")
        self.assertEqual(state["retry_count"], 3)
        self.assertIn("timed out after 2 attempts", state["final_response"])

    def test_evaluate_goal_max_steps_hard_stop(self):
        state = {
            "step_count": MAX_AGENT_STEPS,
            "verification_result": {"valid": True},
        }
        state = evaluate_goal(state)
        self.assertEqual(state["evaluation_status"], "exceeded")
        self.assertFalse(state["goal_complete"])
        self.assertIn("exceeded the maximum", state["final_response"])


if __name__ == "__main__":
    unittest.main()
