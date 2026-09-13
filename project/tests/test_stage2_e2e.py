import hashlib
import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add project directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent.graph import graph


class TestStage2EndToEnd(unittest.TestCase):
    @patch("agent.nodes.execute_query")
    @patch("tools.read_project_data.execute_query")
    @patch("services.authorization.execute_query")
    def test_authenticated_read_flow(self, mock_auth_query, mock_tool_query, mock_node_query):
        # 1. Identity lookup query in load_identity_and_memory
        uid = "11111111-1111-1111-1111-111111111111"
        project_id = "22222222-2222-2222-2222-222222222222"
        phone = "15551234567"
        sender_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest()

        # Mock node queries (load_identity, resolve_project)
        def mock_node_exec(query, params=None, sender_hash=None, user_id=None):
            if "agent_users" in query:
                return [{"id": uid, "display_name": "Alice", "role": "site_supervisor", "is_active": True}]
            if "projects" in query:
                return [{"id": project_id, "project_name": "Project Alpha", "project_code": "ALPHA"}]
            return []

        mock_node_query.side_effect = mock_node_exec
        mock_auth_query.return_value = [{"can_read": True}]
        mock_tool_query.return_value = [
            {
                "id": "33333333-3333-3333-3333-333333333333",
                "project_id": project_id,
                "record_type": "expense",
                "record_date": "2026-09-01",
                "title": "Concrete mix",
                "description": "50 bags cement",
                "amount": 450.00,
                "unit": "USD",
                "data": {},
            }
        ]

        initial_state = {
            "incoming_message": "Show expenses for Project Alpha",
            "sender_wa_id": phone,
            "sender_hash": sender_hash,
            "thread_id": "test-thread-stage2",
        }

        result = graph.invoke(initial_state, config={"configurable": {"thread_id": "test-thread-stage2"}})

        self.assertTrue(result.get("goal_complete"))
        self.assertIn("Concrete mix", result.get("final_response", ""))
        self.assertIn("$450.0", result.get("final_response", ""))

    @patch("agent.nodes.execute_query")
    @patch("services.authorization.execute_query")
    def test_unauthorized_user_safe_failure(self, mock_auth_query, mock_node_query):
        uid = "11111111-1111-1111-1111-111111111111"
        project_id = "22222222-2222-2222-2222-222222222222"
        phone = "15551234567"
        sender_hash = hashlib.sha256(phone.encode("utf-8")).hexdigest()

        def mock_node_exec(query, params=None, sender_hash=None, user_id=None):
            if "agent_users" in query:
                return [{"id": uid, "display_name": "Alice", "role": "site_supervisor", "is_active": True}]
            if "projects" in query:
                return [{"id": project_id, "project_name": "Project Alpha", "project_code": "ALPHA"}]
            return []

        mock_node_query.side_effect = mock_node_exec
        mock_auth_query.return_value = [{"can_read": False}]

        initial_state = {
            "incoming_message": "Show expenses for Project Alpha",
            "sender_wa_id": phone,
            "sender_hash": sender_hash,
            "thread_id": "test-thread-denied",
        }

        result = graph.invoke(initial_state, config={"configurable": {"thread_id": "test-thread-denied"}})

        self.assertFalse(result.get("goal_complete"))
        self.assertIn("Access denied", result.get("final_response", ""))


if __name__ == "__main__":
    unittest.main()
