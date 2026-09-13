#!/usr/bin/env python3
"""PostToolUse hook: after editing a services/ file, run its matching unit
test. Deliberately NOT triggered for tools/ or agent/ — those are checked
via `vercel build` / the smoke test instead.

IMPORTANT PROTOCOL DIFFERENCE FROM THE COPILOT VERSION: Antigravity's
PostToolUse hook contract only accepts `{}` on stdout (it is a fire-and-log
event, not a gate — there is no "additionalContext" channel back into the
agent's context the way Copilot's postToolUse hook had). So this script
can't hand failing test output straight back to the model. Instead it
writes results to `.agents/hooks/.last_test_status.json`, and the
`build-orchestrator` subagent's instructions tell it to check that file
after a batch of edits rather than assuming a green hook means green tests.
"""
import json
import subprocess
import sys
from pathlib import Path

STATUS_FILE = Path(__file__).resolve().parent / ".last_test_status.json"
PATH_KEYS = ("path", "filePath", "file_path", "targetFile", "target_file")


def extract_path(tool_call: dict) -> str:
    args = tool_call.get("args", {}) or {}
    for key in PATH_KEYS:
        value = args.get(key)
        if isinstance(value, str):
            return value
    return ""


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    tool_call = payload.get("toolCall", {}) or {}
    path = extract_path(tool_call)

    if path.startswith("project/services/"):
        test_guess = path.replace("project/services/", "project/tests/services/", 1).replace(".py", "_test.py")
        result = subprocess.run(
            ["python3", "-m", "pytest", test_guess, "-q"],
            capture_output=True,
            text=True,
            check=False,
        )
        STATUS_FILE.write_text(json.dumps({
            "path": path,
            "test_file": test_guess,
            "returncode": result.returncode,
            "stdout_tail": result.stdout[-2000:],
            "stderr_tail": result.stderr[-2000:],
        }, indent=2))

    print(json.dumps({}))


if __name__ == "__main__":
    main()
