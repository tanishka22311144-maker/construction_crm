import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch
from services.audit import (
    check_and_start_message_dedup,
    check_write_idempotency,
    complete_message_dedup,
    load_recent_chat_history,
    record_chat_session,
)


class TestAuditService(unittest.TestCase):
    @patch("services.audit.execute_query")
    def test_dedup_new_message(self, mock_exec):
        mock_exec.return_value = []  # Not in DB yet
        res = check_and_start_message_dedup("msg_new_123", "sender_hash_abc")
        self.assertFalse(res["is_duplicate"])
        self.assertEqual(res["status"], "new")

    @patch("services.audit.execute_query")
    def test_dedup_existing_complete_message(self, mock_exec):
        mock_exec.return_value = [{"status": "complete", "run_id": "11111111-1111-1111-1111-111111111111"}]
        res = check_and_start_message_dedup("msg_dup_456", "sender_hash_abc")
        self.assertTrue(res["is_duplicate"])
        self.assertEqual(res["status"], "complete")

    @patch("services.audit.execute_query")
    def test_load_recent_chat_history(self, mock_exec):
        mock_exec.return_value = [
            {"user_message": "Earlier question", "assistant_reply": "Earlier answer", "created_at": "2026-09-19 12:00:00"},
            {"user_message": "Latest question", "assistant_reply": "Latest answer", "created_at": "2026-09-19 12:05:00"},
        ]
        history = load_recent_chat_history("user-123")
        self.assertEqual(len(history), 2)
        # Should be sorted chronologically
        self.assertEqual(history[0]["user_message"], "Latest question")
        # Verify default 2.0 hour cutoff passed in query params
        args, kwargs = mock_exec.call_args
        sql_query, params = args[0], args[1]
        self.assertIn("INTERVAL '1 hour'", sql_query)
        self.assertEqual(params, ("user-123", 2.0, 6))

    @patch("services.audit.execute_query")
    def test_load_recent_chat_history_cutoff_disabled(self, mock_exec):
        mock_exec.return_value = []
        history = load_recent_chat_history("user-123", inactivity_cutoff_hours=0)
        self.assertEqual(history, [])
        args, kwargs = mock_exec.call_args
        sql_query, params = args[0], args[1]
        self.assertNotIn("INTERVAL '1 hour'", sql_query)
        self.assertEqual(params, ("user-123", 6))

    @patch("services.audit.execute_query")
    def test_check_write_idempotency_found(self, mock_exec):
        mock_exec.return_value = [{
            "id": "rec-123",
            "project_id": "proj-abc",
            "title": "Expense",
            "amount": 10000.0,
        }]
        res = check_write_idempotency("key-xyz", "proj-abc", user_id="user-1", window_minutes=5)
        self.assertIsNotNone(res)
        self.assertEqual(res["id"], "rec-123")
        args, kwargs = mock_exec.call_args
        sql_query, params = args[0], args[1]
        self.assertIn("INTERVAL '1 minute'", sql_query)
        self.assertEqual(params, ("proj-abc", "key-xyz", 5))

    @patch("services.audit.execute_query")
    def test_check_write_idempotency_not_found(self, mock_exec):
        mock_exec.return_value = []
        res = check_write_idempotency("key-none", "proj-abc")
        self.assertIsNone(res)

    def test_check_write_idempotency_missing_params(self):
        self.assertIsNone(check_write_idempotency("", "proj-abc"))
        self.assertIsNone(check_write_idempotency("key", ""))


if __name__ == "__main__":
    unittest.main()
