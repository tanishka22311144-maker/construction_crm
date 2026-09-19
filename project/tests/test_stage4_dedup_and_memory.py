import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from api.index import app
from agent.nodes import load_identity_and_memory


class TestStage4DedupAndMemory(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    @patch("api.index.complete_message_dedup")
    @patch("api.index.check_and_start_message_dedup")
    @patch("agent.graph.graph.invoke")
    def test_webhook_deduplication_prevents_duplicate_run(self, mock_invoke, mock_dedup, mock_complete):
        # 1st time: new message
        mock_dedup.return_value = {"is_duplicate": False, "status": "new"}
        mock_invoke.return_value = {"final_response": "Hello", "goal_complete": True}

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.dup_test_1",
                                        "from": "918698510857",
                                        "text": {"body": "First call"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        resp1 = self.client.post("/api/index", json=payload)
        self.assertEqual(resp1.status_code, 200)
        self.assertEqual(resp1.json()["status"], "ok")
        self.assertEqual(mock_invoke.call_count, 1)

        # 2nd time: redelivery of same message_id
        mock_dedup.return_value = {"is_duplicate": True, "status": "complete"}
        resp2 = self.client.post("/api/index", json=payload)
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(resp2.json()["status"], "already_processed")
        # Graph MUST NOT be invoked a second time
        self.assertEqual(mock_invoke.call_count, 1)

    @patch("agent.nodes.load_recent_chat_history")
    @patch("agent.nodes.execute_query")
    def test_load_identity_and_memory_injects_conversation_context(self, mock_query, mock_history):
        mock_query.return_value = [
            {"id": "u1", "display_name": "Alice", "role": "site_supervisor", "is_active": True}
        ]
        mock_history.return_value = [
            {"user_message": "Which projects are active?", "assistant_reply": "Metro Line Extension"},
        ]

        state = {
            "sender_hash": "some_hash",
            "incoming_message": "What did I ask earlier?",
        }
        state = load_identity_and_memory(state)

        self.assertEqual(state["user_id"], "u1")
        messages = state.get("messages", [])
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[0]["content"], "Which projects are active?")
        self.assertEqual(messages[1]["content"], "Metro Line Extension")
        self.assertEqual(messages[2]["content"], "What did I ask earlier?")


if __name__ == "__main__":
    unittest.main()
