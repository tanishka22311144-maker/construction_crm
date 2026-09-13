import unittest
from unittest.mock import patch
import sys
from pathlib import Path

# Add project directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.authorization import authorize, check_user_project_read_access


class TestAuthorization(unittest.TestCase):
    def test_missing_user_id_fails(self):
        result = authorize(user_id=None, project_id="proj-123", operation="read_project_data")
        self.assertFalse(result["allowed"])
        self.assertIn("Unauthenticated", result["reason"])

    def test_missing_project_id_fails(self):
        result = authorize(user_id="user-123", project_id=None, operation="read_project_data")
        self.assertFalse(result["allowed"])
        self.assertIn("missing or unresolved", result["reason"])

    @patch("services.authorization.execute_query")
    def test_authorized_read_access_success(self, mock_execute):
        mock_execute.return_value = [{"can_read": True}]
        result = authorize(user_id="user-123", project_id="proj-123", operation="read_project_data")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["risk_level"], "low")
        self.assertFalse(result["human_approval_required"])

    @patch("services.authorization.execute_query")
    def test_denied_read_access_no_permission(self, mock_execute):
        mock_execute.return_value = [{"can_read": False}]
        result = authorize(user_id="user-123", project_id="proj-123", operation="read_project_data")
        self.assertFalse(result["allowed"])

    @patch("services.authorization.execute_query")
    def test_denied_read_access_no_rows(self, mock_execute):
        mock_execute.return_value = []
        result = authorize(user_id="user-123", project_id="proj-123", operation="read_project_data")
        self.assertFalse(result["allowed"])

    @patch("services.authorization.execute_query")
    def test_db_exception_fails_closed(self, mock_execute):
        mock_execute.side_effect = Exception("DB connection down")
        result = authorize(user_id="user-123", project_id="proj-123", operation="read_project_data")
        self.assertFalse(result["allowed"])


if __name__ == "__main__":
    unittest.main()
