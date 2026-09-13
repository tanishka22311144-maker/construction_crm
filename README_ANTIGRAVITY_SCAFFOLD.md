# What this scaffold is

Your construction-CRM WhatsApp agent project, restructured for Google
Antigravity instead of GitHub Copilot. This version incorporates the full
`PROJECT_SPEC.md` (1058 lines — the first upload only had files that
*referenced* it, not its content) and corrects two things the earlier
version got wrong without it:

1. `project/api/index.py` is now a **FastAPI** app (PROJECT_SPEC.md §1:
   "Vercel Python Function (FastAPI)"), not a generic handler function.
2. The app code lives in a **`project/` subdirectory**, sibling to
   `.agents/` at repo root — matching PROJECT_SPEC.md §3's note that
   `.github/` (now `.agents/`) "exists at the repo root alongside
   `project/`". The first version put `agent/`/`api/` directly at repo
   root; that was wrong.

## Layout

```
PROJECT_SPEC.md                # NEW — full end-state spec, now included verbatim
IMPLEMENTATION_STAGES.md        # unchanged — your 6-stage build sequence
AGENTS.md                       # root instructions, auto-loaded by Antigravity
.agents/
  rules/                        # database.md, langgraph.md, security.md, tools.md
  agents/                       # build-orchestrator/agent.md, reviewer/agent.md
  skills/                       # idempotency-key, supabase-rls, verification-envelope, whatsapp-approval-flow
  hooks.json                    # see .agents/hooks/README.md for the Copilot -> Antigravity mapping
  hooks/*.py
project/                        # the actual deployable app (PROJECT_SPEC.md §3)
  api/
    index.py                    # FastAPI Stage 1 webhook handler
  agent/
    __init__.py
    state.py                    # full AgentState from PROJECT_SPEC.md §4
    nodes.py                    # your existing Stage 1 code, unchanged
    graph.py                    # your existing Stage 1 code, unchanged
    instructions.md             # your existing Stage 1 runtime prompt, unchanged
  tests/
    smoke_test.sh
  requirements.txt
  vercel.json                   # matches PROJECT_SPEC.md §17's example exactly
```

`project/tools/`, `project/services/`, `project/supabase/` don't exist yet
— they're Stage 2+ deliverables (`IMPLEMENTATION_STAGES.md`). Don't create
them early; that's exactly the "don't build ahead of the stage" rule
`AGENTS.md` and the `build-orchestrator` subagent both enforce.

## What changed from the previous scaffold

- `project/api/index.py` — rewritten as FastAPI (`@app.get`/`@app.post` on
  `/api/index`), matching §1/§17. The env var names it reads
  (`META_VERIFY_TOKEN`, `META_WHATSAPP_TOKEN`, `META_PHONE_NUMBER_ID`) are
  still not named anywhere in `PROJECT_SPEC.md` itself — that's a real gap
  in the spec, not something I missed, so treat them as placeholders and
  rename to whatever your actual Meta app config uses.
- `project/vercel.json` — now byte-for-byte the example from §17
  (`functions.api/index.py.maxDuration: 60`), instead of an invented
  `runtime` key.
- `project/requirements.txt` — added `fastapi` and `langgraph` explicitly.
- Every path reference in `.agents/rules/*.md`, the two `agent.md`
  subagent files, and the hook scripts (`run_scoped_tests.py`,
  `vercel_build_check.py`) now points at `project/...` instead of a bare
  top-level path.
- `AGENTS.md` now cites §3's instruction precedence and §19's ownership
  table directly, and explains the `project/` vs `.agents/` sibling
  relationship instead of leaving it implicit.

## Still worth double-checking once you're in Antigravity

- `.agents/hooks/README.md` — same caveats as before: `PostToolUse`/`Stop`
  are notification-only in Antigravity's protocol, and the file-edit tool's
  exact argument key isn't confirmed. Nothing about having the full spec
  changed that; it's a property of Antigravity's hook system, not your
  project.
- `project/supabase/README.md` doesn't exist yet — `PROJECT_SPEC.md` §13
  describes the session-variable RLS pattern in general terms
  (`app.current_user_id`, `service_role` never leaving
  `services/database.py`) but the actual README with `bind_request_context()`
  and role setup is a Stage 2 deliverable per `IMPLEMENTATION_STAGES.md`,
  not something to write ahead of time.
