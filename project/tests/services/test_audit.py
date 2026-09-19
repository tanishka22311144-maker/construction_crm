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


if __name__ == "__main__":
    unittest.main()
