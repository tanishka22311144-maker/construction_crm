---
name: verification-envelope
description: Strict result envelope and read-back verification pattern for any write tool
---

# Verification envelope

Use this exact shape for every write tool result:

```json
{
  "success": true,
  "operation": "add_project_row",
  "operation_id": "uuid",
  "record_id": "uuid",
  "affected_rows": 1,
  "data": {},
  "warnings": [],
  "error": null
}
```

Validate it with:

```python
def validate_write_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return failure("INVALID_RESULT_TYPE")
    if result.get("success") is not True:
        return failure("TOOL_REPORTED_FAILURE")
    if result.get("affected_rows") != 1:
        return failure("UNEXPECTED_AFFECTED_ROWS")
    if not result.get("record_id"):
        return failure("MISSING_RECORD_ID")
    return {"success": True, "code": "WRITE_RESULT_VALID"}
```

Then independently re-read and compare — never infer correctness from the
write call's own response:

```python
def verify_insert(project_id, expected, write_result):
    stored = get_record_by_id(write_result["record_id"])
    if stored is None:
        return failure("RECORD_NOT_FOUND_AFTER_WRITE")
    if stored["project_id"] != project_id:
        return failure("PROJECT_ID_MISMATCH")
    mismatches = compare_normalized_values(expected=expected, actual=stored)
    if mismatches:
        return failure("READ_BACK_MISMATCH", details=mismatches)
    return {"success": True, "code": "WRITE_VERIFIED", "verified_record": stored}
```

A tool is not done until both functions above pass for its write path.
