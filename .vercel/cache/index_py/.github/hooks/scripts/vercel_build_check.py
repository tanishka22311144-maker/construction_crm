#!/usr/bin/env python3
"""postToolUse hook: after editing anything that affects the deployable
function (api/, tools/, agent/, services/, vercel.json), run a local
`vercel build` to catch import errors, bad routing config, or missing
dependencies immediately. This costs no Copilot premium requests — it's
just the Vercel CLI — so it's safe to run often, unlike a model-backed
review."""
import subprocess
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ""

WATCHED_PREFIXES = ("api/", "tools/", "agent/", "services/")
WATCHED_FILES = ("vercel.json", "requirements.txt")

if path.startswith(WATCHED_PREFIXES) or path in WATCHED_FILES:
    result = subprocess.run(
        ["vercel", "build", "--yes"], capture_output=True, text=True, timeout=90
    )
    if result.returncode != 0:
        print(
            '{"behavior": "allow", "additionalContext": '
            + repr(result.stdout[-2000:] + result.stderr[-2000:])
            + "}"
        )
        sys.exit(0)

print('{"behavior": "allow"}')
