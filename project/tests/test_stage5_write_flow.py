import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch, MagicMock
from agent.graph import graph


class TestStage5WriteFlow(unittest.TestCase):
    @patch("services.database.execute_query")
    @patch("services.audit.execute_query")
    @patch("tools.add_project_row.execute_query")
    @patch("services.authorization.execute_query")
    @patch("agent.nodes.execute_query")
    @patch("agent.nodes._get_llm_reply")
    def test_add_project_row_graph_flow(
        self,
        mock_llm,
        mock_node_exec,
        mock_auth_exec,
        mock_tool_exec,
        mock_audit_exec,
        mock_db_exec,
    ):
        # 1. LLM JSON output selecting add_project_row
        mock_llm.return_value = '{"intent": "write", "selected_tool": "add_project_row", "project_name": "Metro Line Extension", "tool_arguments": {"record_type": "expense", "title": "Fuel", "amount": 2500, "unit": "INR"}}'

        # 2. Database mocks
        def mock_query_router(sql, params=None, **kwargs):
            sql_clean = " ".join(sql.split()).upper()
            if "FROM PUBLIC.AGENT_USERS" in sql_clean:
                return [{"id": "11111111-1111-1111-1111-111111111111", "display_name": "Site Supervisor", "role": "site_supervisor", "is_active": True}]
            if "FROM PUBLIC.CHAT_SESSIONS" in sql_clean:
                return []
            if "FROM PUBLIC.PROJECTS" in sql_clean:
                return [{"id": "22222222-2222-2222-2222-222222222222", "project_name": "Metro Line Extension", "project_code": "MLE-01"}]
            if "FROM PUBLIC.USER_PROJECT_ACCESS" in sql_clean:
                return [{"can_add_rows": True, "can_read": True}]
            if "INSERT INTO PUBLIC.PROJECT_RECORDS" in sql_clean:
                return [{
                    "id": "33333333-3333-3333-3333-333333333333",
                    "project_id": "22222222-2222-2222-2222-222222222222",
                    "record_type": "expense",
                    "record_date": "2026-09-22",
                    "title": "Fuel",
                    "description": None,
                    "amount": 2500.0,
                    "unit": "INR",
                    "data": {"idempotency_key": "abc"},
                    "created_at": "2026-09-22T10:00:00Z",
                }]
            if "SELECT ID, PROJECT_ID, RECORD_TYPE" in sql_clean and "FROM PUBLIC.PROJECT_RECORDS" in sql_clean:
                # Read-back verification query
                return [{
                    "id": "33333333-3333-3333-3333-333333333333",
                    "project_id": "22222222-2222-2222-2222-222222222222",
                    "record_type": "expense",
                    "record_date": "2026-09-22",
                    "title": "Fuel",
                    "description": None,
                    "amount": 2500.0,
                    "unit": "INR",
                    "data": {"idempotency_key": "abc"},
                    "created_by": "11111111-1111-1111-1111-111111111111",
                    "created_at": "2026-09-22T10:00:00Z",
                }]
            if "INSERT INTO PUBLIC.AGENT_EVENTS" in sql_clean or "INSERT INTO PUBLIC.AGENT_RUNS" in sql_clean:
                return []
            return []

        mock_node_exec.side_effect = mock_query_router
        mock_auth_exec.side_effect = mock_query_router
        mock_tool_exec.side_effect = mock_query_router
        mock_audit_exec.side_effect = mock_query_router
        mock_db_exec.side_effect = mock_query_router

        initial_state = {
            "incoming_message": "Add a fuel expense of 2500 to Metro Line Extension",
            "sender_wa_id": "15551234567",
            "sender_hash": "d6736136ea896c1bfdc553e0e86e702c70d060d805696ca3e4e9e0961353860a",
            "message_id": "wamid.write_test_1",
            "thread_id": "test-thread-write",
        }

        result = graph.invoke(initial_state, config={"configurable": {"thread_id": "test-thread-write"}})

        # Assertions
        self.assertTrue(result.get("goal_complete"))
        self.assertEqual(result.get("selected_tool"), "add_project_row")
        self.assertIsNotNone(result.get("verified_record"))
        self.assertEqual(result["verified_record"]["id"], "33333333-3333-3333-3333-333333333333")
        final_reply = result.get("final_response", "")
        self.assertIn("recorded", final_reply.lower())
        self.assertIn("fuel", final_reply.lower())


if __name__ == "__main__":
    unittest.main()
