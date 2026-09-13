#!/usr/bin/env python3
"""postToolUse hook: after editing a services/ file, run its matching unit
test. Deliberately NOT triggered for tools/ or agent/ — those are checked
via `vercel build` / the smoke test instead, since pure-function unit
tests here don't add much over an actual running preview, and we want to
keep this hook cheap and fast during iterative edits."""
import subprocess
import sys

path = sys.argv[1] if len(sys.argv) > 1 else ""

if path.startswith("services/"):
    test_guess = path.replace("services/", "tests/services/").replace(
        ".py", "_test.py"
    )
    subprocess.run(["python3", "-m", "pytest", test_guess, "-q"], check=False)

print('{"behavior": "allow"}')
