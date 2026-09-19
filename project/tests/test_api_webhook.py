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


class TestApiWebhook(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_verify_webhook_get(self):
        with patch.dict("os.environ", {"META_VERIFY_TOKEN": "my_secret_token"}):
            resp = self.client.get("/api/index?hub.mode=subscribe&hub.verify_token=my_secret_token&hub.challenge=123456")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.text, "123456")

    @patch("api.index._send_whatsapp_reply")
    @patch("agent.graph.graph.invoke")
    def test_receive_webhook_post_success(self, mock_invoke, mock_reply):
        mock_invoke.return_value = {
            "final_response": "Test response",
            "goal_complete": True,
        }

        payload = {
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messages": [
                                    {
                                        "id": "wamid.123",
                                        "from": "918698510857",
                                        "text": {"body": "Hello CRM"},
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        resp = self.client.post("/api/index", json=payload)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["final_response"], "Test response")
        self.assertTrue(data["goal_complete"])

        # Ensure graph was invoked with proper config and state
        self.assertTrue(mock_invoke.called)
        state_arg, config_arg = mock_invoke.call_args[0][0], mock_invoke.call_args[1]["config"]
        self.assertIn("thread_id", state_arg)
        self.assertTrue(state_arg["thread_id"].startswith("wa-"))
        self.assertIn("thread_id", config_arg["configurable"])
        self.assertIn("run_id", config_arg["metadata"])


if __name__ == "__main__":
    unittest.main()
