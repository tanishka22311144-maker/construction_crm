import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import unittest
from unittest.mock import patch
from services.verification import (
    validate_write_result,
    compare_normalized_values,
    verify_insert,
)


class TestVerificationWrite(unittest.TestCase):
    def test_validate_write_result_success(self):
        envelope = {
            "success": True,
            "operation": "add_project_row",
            "operation_id": "op-123",
            "record_id": "rec-456",
            "affected_rows": 1,
            "data": {},
            "warnings": [],
            "error": None,
        }
        res = validate_write_result(envelope)
        self.assertTrue(res["valid"])
        self.assertEqual(res["code"], "WRITE_RESULT_VALID")

    def test_validate_write_result_missing_record_id(self):
        envelope = {
            "success": True,
            "operation": "add_project_row",
            "affected_rows": 1,
            "record_id": None,
        }
        res = validate_write_result(envelope)
        self.assertFalse(res["valid"])
        self.assertEqual(res["code"], "MISSING_RECORD_ID")

    def test_validate_write_result_wrong_affected_rows(self):
        envelope = {
            "success": True,
            "operation": "add_project_row",
            "affected_rows": 2,
            "record_id": "rec-456",
        }
        res = validate_write_result(envelope)
        self.assertFalse(res["valid"])
        self.assertEqual(res["code"], "UNEXPECTED_AFFECTED_ROWS")

    def test_compare_normalized_values_match(self):
        expected = {
            "record_type": "expense",
            "title": "Fuel",
            "amount": 2500,
            "unit": "inr",
            "data": {"category": "Fuel"},
        }
        actual = {
            "record_type": "EXPENSE",
            "title": "fuel",
            "amount": 2500.0,
            "unit": "INR",
            "data": {"category": "Fuel", "other": "val"},
        }
        mismatches = compare_normalized_values(expected, actual)
        self.assertEqual(mismatches, [])

    def test_compare_normalized_values_mismatch(self):
        expected = {"record_type": "expense", "amount": 2500}
        actual = {"record_type": "expense", "amount": 3000}
        mismatches = compare_normalized_values(expected, actual)
        self.assertEqual(len(mismatches), 1)
        self.assertIn("amount mismatch", mismatches[0])

    @patch("services.database.execute_query")
    def test_verify_insert_success(self, mock_exec):
        mock_exec.return_value = [{
            "id": "rec-123",
            "project_id": "proj-abc",
            "record_type": "expense",
            "title": "Fuel",
            "amount": 2500.0,
            "unit": "INR",
            "data": {},
        }]
        res = verify_insert(
            project_id="proj-abc",
            expected={"record_type": "expense", "title": "Fuel", "amount": 2500},
            write_result={"record_id": "rec-123"},
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["code"], "WRITE_VERIFIED")

    @patch("services.database.execute_query")
    def test_verify_insert_record_not_found(self, mock_exec):
        mock_exec.return_value = []
        res = verify_insert(
            project_id="proj-abc",
            expected={},
            write_result={"record_id": "rec-missing"},
        )
        self.assertFalse(res["success"])
        self.assertEqual(res["code"], "RECORD_NOT_FOUND_AFTER_WRITE")


if __name__ == "__main__":
    unittest.main()
