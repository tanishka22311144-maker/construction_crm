import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch
from tools.add_project_row import add_project_row


class TestAddProjectRow(unittest.TestCase):
    @patch("tools.add_project_row.check_write_idempotency")
    @patch("tools.add_project_row.execute_query")
    def test_add_project_row_success(self, mock_exec, mock_idemp):
        mock_idemp.return_value = None  # Not previously inserted
        mock_exec.return_value = [{
            "id": "11111111-1111-1111-1111-111111111111",
            "project_id": "22222222-2222-2222-2222-222222222222",
            "record_type": "expense",
            "record_date": "2026-09-22",
            "title": "Fuel",
            "description": None,
            "amount": 2500.0,
            "unit": "INR",
            "data": {"category": "Fuel"},
            "created_at": "2026-09-22T10:00:00Z",
        }]

        result = add_project_row(
            project_id="22222222-2222-2222-2222-222222222222",
            record_type="expense",
            title="Fuel",
            amount=2500,
            unit="INR",
            data={"category": "Fuel"},
            message_id="msg-12345",
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["affected_rows"], 1)
        self.assertEqual(result["record_id"], "11111111-1111-1111-1111-111111111111")
        self.assertEqual(result["data"]["amount"], 2500.0)

    @patch("tools.add_project_row.check_write_idempotency")
    def test_add_project_row_idempotent_replay(self, mock_idemp):
        # Existing record found with same key
        mock_idemp.return_value = {
            "id": "existing-uuid-123",
            "project_id": "22222222-2222-2222-2222-222222222222",
            "record_type": "expense",
            "title": "Fuel",
            "amount": 2500.0,
        }

        result = add_project_row(
            project_id="22222222-2222-2222-2222-222222222222",
            record_type="expense",
            title="Fuel",
            amount=2500,
            message_id="msg-12345",
        )

        self.assertTrue(result["success"])
        self.assertTrue(result.get("idempotent_replay"))
        self.assertEqual(result["record_id"], "existing-uuid-123")

    def test_add_project_row_invalid_type(self):
        result = add_project_row(
            project_id="22222222-2222-2222-2222-222222222222",
            record_type="unsupported_type",
            title="Invalid",
        )
        self.assertFalse(result["success"])
        self.assertIn("Invalid record_type", result["error"])

    def test_add_project_row_invalid_amount(self):
        result = add_project_row(
            project_id="22222222-2222-2222-2222-222222222222",
            record_type="expense",
            title="Fuel",
            amount="not_a_number",
        )
        self.assertFalse(result["success"])
        self.assertIn("Invalid amount", result["error"])


if __name__ == "__main__":
    unittest.main()
