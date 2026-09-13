import unittest
from unittest.mock import patch
import sys
from pathlib import Path

# Add project directory to sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from tools.read_project_data import read_project_data


class TestReadProjectData(unittest.TestCase):
    def test_missing_project_id(self):
        result = read_project_data(project_id="")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["count"], 0)

    @patch("tools.read_project_data.execute_query")
    def test_read_project_data_success(self, mock_execute):
        mock_execute.return_value = [
            {"id": "rec-1", "title": "Concrete pour", "record_type": "daily_log", "amount": None},
            {"id": "rec-2", "title": "Steel rebar", "record_type": "expense", "amount": 1250.00},
        ]
        result = read_project_data(project_id="proj-123", record_type="expense", limit=10, user_id="user-123")
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["records"]), 2)

    @patch("tools.read_project_data.execute_query")
    def test_limit_clamped_to_50(self, mock_execute):
        mock_execute.return_value = []
        read_project_data(project_id="proj-123", limit=100, user_id="user-123")
        # Verify clamped limit passed in params
        args, kwargs = mock_execute.call_args
        params = args[1]
        self.assertEqual(params[-1], 50)


if __name__ == "__main__":
    unittest.main()
