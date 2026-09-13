# Hook mapping: Copilot `guardrails.json` → Antigravity `hooks.json`

This project originally had a GitHub Copilot hook set (`guardrails.json` +
5 Python scripts under `.github/hooks/scripts/`). Antigravity's hook
system is genuinely different, not just differently named — three things
changed on the way over:

## 1. Event names

| Copilot event      | Antigravity event | Notes                                   |
|---------------------|--------------------|------------------------------------------|
| `preToolUse`         | `PreToolUse`       | same idea                                |
| `postToolUse`        | `PostToolUse`      | same idea, but see limitation #2 below   |
| `permissionRequest`  | `PreToolUse`       | folded in — Antigravity has no separate permission-request event; a deny at PreToolUse serves the same purpose |
| `subagentStop`       | `Stop`             | **not equivalent** — see limitation #3   |

## 2. Stdout contract is stricter and mostly one-way

Antigravity expects an exact protojson shape per event:
- `PreToolUse` → `{"decision": "allow" | "deny" | "ask" | "force_ask", "reason": "..."}`
- `PostToolUse` → `{}` (no gating, no context injection back to the model)
- `Stop` → `{}` (notification only)

Copilot's hooks could return `{"behavior": "allow", "additionalContext": "..."}`
from a `postToolUse` hook and have that text fed back to the model. Antigravity's
`PostToolUse` can't do that — so `run_scoped_tests.py` and
`vercel_build_check.py` now write their results to
`.agents/hooks/.last_test_status.json` / `.last_build_status.json` instead,
and the `build-orchestrator` subagent is instructed to check those files
itself after a batch of edits.

## 3. No subagent-specific stop event, and Stop can't block

The original `enforce_clean_review.py` fired specifically when the
`reviewer` subagent finished, and could return `{"behavior": "block", ...}`
to actually prevent the orchestrator from moving on with unresolved
findings. Antigravity's `Stop` event:
- fires on the (sub)agent loop stopping generally, without confirmed
  per-subagent targeting in the matcher, and
- only accepts `{}` on stdout — it cannot block continuation.

The adapted script now just leaves a flag file
(`.agents/hooks/.review_flag.json`) when it finds an unchecked box in the
recent transcript. Enforcement is therefore a standing instruction, not a
hard hook gate: `build-orchestrator`'s `agent.md` and the root `AGENTS.md`
both tell the orchestrator to check for that flag file before treating a
Stage 2 / 5 / 6 checkpoint as passed.

## 4. Tool-name matchers are best-effort

Only `run_command` and its `CommandLine` argument field are confirmed
tool/arg names for Antigravity. The file-edit tool name(s) and their path
argument key aren't confirmed the same way, so `hooks.json`'s matcher for
edit-like tools uses a loose regex (`.*(write|edit|create).*`) and the
scripts probe several likely argument keys (`path`, `filePath`,
`file_path`, `targetFile`, `target_file`). **Once you can inspect one real
`toolCall` payload from your Antigravity build (e.g. by having a hook
temporarily dump stdin to a file), tighten the matcher and the key list
to match exactly** — a loose matcher risks either missing edits it should
catch or running on tool calls it shouldn't.

## What didn't need to change

`deny_destructive_commands.py`'s substring-deny logic, and the underlying
security intent of every hook, transferred as-is — only the transport
(event names, stdin/stdout shape) changed.
