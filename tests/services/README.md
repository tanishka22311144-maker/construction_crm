# services/ unit tests

One test file per file in `services/`, matched 1:1 by name:
`services/authorization.py` → `tests/services/authorization_test.py`, etc.

This mapping isn't cosmetic — the `run_scoped_tests.py` postToolUse hook
(`.github/hooks/guardrails.json`) does a literal path substitution
(`services/` → `tests/services/`, `.py` → `_test.py`) to find and run the
matching test automatically after every edit to a `services/` file. If a
test file doesn't follow this exact naming pattern, the hook will silently
find nothing to run rather than erroring — so when you add a new
`services/*.py` file, add its test file under this exact name at the same
time.

`tools/` and `agent/` are intentionally NOT covered here — those are
checked via `vercel build` and `tests/smoke_test.sh` instead. See
`.github/copilot-instructions.md` for why.
