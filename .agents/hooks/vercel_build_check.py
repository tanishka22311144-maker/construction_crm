#!/usr/bin/env python3
"""PostToolUse hook: after editing anything that affects the deployable
function (api/, tools/, agent/, services/, vercel.json), run a local
`vercel build` to catch import errors, bad routing config, or missing
dependencies immediately.

Same protocol note as run_scoped_tests.py: PostToolUse must emit `{}` on
stdout, so build failures can't be injected straight back into context.
This writes to `.agents/hooks/.last_build_status.json`; the
build-orchestrator subagent is instructed to check it after a batch of
edits rather than assuming silence means success.
"""
import json
import subprocess
import sys
from pathlib import Path

STATUS_FILE = Path(__file__).resolve().parent / ".last_build_status.json"
PATH_KEYS = ("path", "filePath", "file_path", "targetFile", "target_file")

WATCHED_PREFIXES = ("project/api/", "project/tools/", "project/agent/", "project/services/")
WATCHED_FILES = ("project/vercel.json", "project/requirements.txt")


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

    if path.startswith(WATCHED_PREFIXES) or path in WATCHED_FILES:
        try:
            result = subprocess.run(
                ["vercel", "build", "--yes"], capture_output=True, text=True, timeout=90,
                cwd="project",  # vercel.json lives in project/, not repo root
            )
            STATUS_FILE.write_text(json.dumps({
                "path": path,
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-2000:],
                "stderr_tail": result.stderr[-2000:],
            }, indent=2))
        except Exception as exc:  # pragma: no cover - defensive
            STATUS_FILE.write_text(json.dumps({"path": path, "error": str(exc)}, indent=2))

    print(json.dumps({}))


if __name__ == "__main__":
    main()
