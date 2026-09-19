import sys
from pathlib import Path

# Add project root to sys.path
PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from services.verification import validate_read_result, classify_error, MAX_ROW_COUNT


class TestVerification(unittest.TestCase):
    def test_valid_read_result(self):
        result = {
            "status": "success",
            "project_id": "proj-123",
            "record_type": "expense",
            "count": 2,
            "records": [
                {"id": "r1", "amount": 100},
                {"id": "r2", "amount": 200},
            ],
        }
        res = validate_read_result(result)
        self.assertTrue(res["valid"])
        self.assertEqual(res["code"], "READ_RESULT_VALID")
        self.assertEqual(res["row_count"], 2)

    def test_invalid_type(self):
        res = validate_read_result("not a dict")
        self.assertFalse(res["valid"])
        self.assertEqual(res["code"], "INVALID_RESULT_TYPE")

    def test_tool_reported_failure(self):
        result = {"status": "error", "error": "Connection timed out"}
        res = validate_read_result(result)
        self.assertFalse(res["valid"])
        self.assertEqual(res["code"], "TOOL_REPORTED_FAILURE")
        self.assertTrue(res["is_transient"])

    def test_exceeded_max_rows(self):
        result = {
            "status": "success",
            "records": [{"id": f"r{i}"} for i in range(MAX_ROW_COUNT + 10)],
        }
        res = validate_read_result(result)
        self.assertFalse(res["valid"])
        self.assertEqual(res["code"], "EXCEEDED_MAX_ROW_COUNT")

    def test_error_classification(self):
        # Transient
        self.assertTrue(classify_error("504 Gateway Timeout")["is_transient"])
        self.assertTrue(classify_error("connection reset by peer")["is_transient"])
        self.assertTrue(classify_error("cannot assign requested address")["is_transient"])

        # Fatal / Non-transient
        self.assertFalse(classify_error("permission denied for relation project_records")["is_transient"])
        self.assertFalse(classify_error("syntax error at or near 'SELECT'")["is_transient"])
        self.assertFalse(classify_error("duplicate key value violates unique constraint")["is_transient"])


if __name__ == "__main__":
    unittest.main()
