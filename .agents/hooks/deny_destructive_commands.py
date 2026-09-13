#!/usr/bin/env python3
"""PreToolUse hook (matcher: run_command): auto-deny shell commands that
could touch production data or infrastructure directly from an agent
session.

Antigravity CLI sends the command line under toolCall.args.CommandLine
(confirmed field name/casing) for the run_command tool. Stdout must be
protojson: {"decision": "allow" | "deny" | "ask" | "force_ask", "reason": "..."}
"""
import json
import sys

DENY_SUBSTRINGS = [
    "supabase db reset",
    "supabase db push --linked",
    "rm -rf",
    "DROP TABLE",
    "DROP DATABASE",
    "vercel --prod",
    "TRUNCATE",
    # AGENTS.md "Git workflow — always follow": commit only to main, and
    # never commit the scaffold/ authoring folder (the .gitignore entry
    # is the primary guard; these are a second layer).
    "git checkout -b",
    "git switch -c",
    "git add scaffold",
    "git add ./scaffold",
    "git commit scaffold",
]


def main() -> None:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        payload = {}

    tool_call = payload.get("toolCall", {}) or {}
    args = tool_call.get("args", {}) or {}
    cmd = args.get("CommandLine") or args.get("commandLine") or args.get("command") or ""

    for bad in DENY_SUBSTRINGS:
        if bad.lower() in cmd.lower():
            print(json.dumps({
                "decision": "deny",
                "reason": f"Blocked destructive command pattern: {bad}",
            }))
            return

    print(json.dumps({"decision": "allow"}))


if __name__ == "__main__":
    main()
