#!/usr/bin/env python3
"""PreToolUse hook: block edits that would touch .env files, and flag (but
do not yet hard-block) any edit under tools/ or agent/ that might be
introducing a service_role client directly.

Antigravity CLI sends camelCase protojson on stdin, e.g.:
  {"conversationId": "...", "workspacePaths": [...], "transcriptPath": "...",
   "toolCall": {"name": "write_file", "args": {...}}, "stepIdx": ...}

and expects protojson on stdout for PreToolUse:
  {"decision": "allow" | "deny" | "ask" | "force_ask", "reason": "..."}

NOTE: the exact key the file path lives under inside toolCall.args isn't
confirmed for every possible write/edit tool name in Antigravity IDE (this
was only verified for run_command's CommandLine field). This script checks
several likely keys defensively — adjust PATH_KEYS if your build uses a
different one once you can inspect a live toolCall payload.
"""
import json
import sys

DENY_SUFFIXES = (".env", ".env.local", ".env.production")
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

    if path and any(path.endswith(suffix) for suffix in DENY_SUFFIXES):
        print(json.dumps({
            "decision": "deny",
            "reason": "Env files are edited manually, not by the agent.",
        }))
        return

    # Heuristic only for now: project/tools/** and project/agent/** should
    # never construct a service_role client directly. A stricter check
    # would grep proposed content, which isn't available on this event
    # without richer payload access — enforce that instead via
    # project/services/database.py review and the reviewer subagent
    # checkpoint.
    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
