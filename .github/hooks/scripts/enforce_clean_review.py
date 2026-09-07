#!/usr/bin/env python3
"""subagentStop hook: fail loudly if verification-auditor or
security-reviewer reported any unchecked box, instead of letting the
orchestrator silently move on."""
import sys

output = sys.argv[1] if len(sys.argv) > 1 else ""

if "[ ]" in output:
    print(
        '{"behavior": "block", '
        '"additionalContext": "Reviewer found unchecked items — resolve them before continuing."}'
    )
    sys.exit(0)

print('{"behavior": "allow"}')
