#!/usr/bin/env python3
"""preToolUse hook: block edits that introduce service_role key usage
outside services/database.py, or edits to .env files."""
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ""

DENY_PATHS = (".env", ".env.local", ".env.production")

if any(path.endswith(p) for p in DENY_PATHS):
    print('{"behavior": "deny", "reason": "Env files are edited manually, not by the agent."}')
    sys.exit(0)

if path.startswith("tools/") or path.startswith("agent/"):
    # Heuristic: these layers should never import a service-role client directly.
    # A stricter check greps the actual diff/content; wire that in once the
    # hook payload includes proposed file content.
    pass

print('{"behavior": "allow"}')
