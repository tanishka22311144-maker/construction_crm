#!/usr/bin/env python3
"""permissionRequest hook: auto-deny shell commands that could touch
production data or infrastructure directly from an agent session."""
import os
import sys

cmd = os.environ.get("COPILOT_REQUESTED_COMMAND", "")

DENY_SUBSTRINGS = [
    "supabase db reset",
    "supabase db push --linked",
    "rm -rf",
    "DROP TABLE",
    "DROP DATABASE",
    "vercel --prod",
    "TRUNCATE",
]

for bad in DENY_SUBSTRINGS:
    if bad.lower() in cmd.lower():
        print(f'{{"behavior": "deny", "reason": "Blocked destructive command pattern: {bad}"}}')
        sys.exit(0)

print('{"behavior": "allow"}')
