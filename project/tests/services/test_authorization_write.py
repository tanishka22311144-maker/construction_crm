import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch
from services.authorization import (
    check_user_project_write_access,
    authorize,
)


class TestAuthorizationWrite(unittest.TestCase):
    @patch("services.authorization.execute_query")
    def test_check_user_project_write_access_granted(self, mock_exec):
        mock_exec.return_value = [{"can_add_rows": True}]
        self.assertTrue(check_user_project_write_access("user-1", "proj-1"))

    @patch("services.authorization.execute_query")
    def test_check_user_project_write_access_denied(self, mock_exec):
        mock_exec.return_value = [{"can_add_rows": False}]
        self.assertFalse(check_user_project_write_access("user-1", "proj-1"))

    @patch("services.authorization.check_user_project_write_access")
    def test_authorize_write_allowed(self, mock_check):
        mock_check.return_value = True
        res = authorize("user-1", "proj-1", operation="add_project_row")
        self.assertTrue(res["allowed"])
        self.assertEqual(res["risk_level"], "medium")

    @patch("services.authorization.check_user_project_write_access")
    def test_authorize_write_denied(self, mock_check):
        mock_check.return_value = False
        res = authorize("user-1", "proj-1", operation="add_project_row")
        self.assertFalse(res["allowed"])
        self.assertIn("does not have permission", res["reason"])


if __name__ == "__main__":
    unittest.main()
