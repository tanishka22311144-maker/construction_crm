# Construction CRM WhatsApp agent — Antigravity instructions

This file is auto-loaded by Antigravity as system instructions on startup.
Keep it under ~12,000 characters — detail that would push it over lives in
`.agents/rules/*.md` instead (see below), which you should also read.

## Two separate instruction layers — don't confuse them

- `agent/instructions.md` — the RUNTIME system prompt loaded by the deployed
  LangGraph agent on every WhatsApp request. Edit it only when you intend to
  change agent behavior in production, and remember changes take effect only
  after the next deploy.
- `AGENTS.md` (this file) + everything under `.agents/` — guidance for you,
  the Antigravity agent, while writing the code that implements the spec
  below. Never let instructions meant for one layer leak into the other.

## Where the spec, build order, and code live

- `PROJECT_SPEC.md` (repo root) — end-state reference: full schema, all four
  tools, the complete graph (§5), the approval checklist (§11), instruction
  precedence (§3: backend authorization > tool validation > LangGraph
  routing > this runtime prompt > the user's current request).
- `IMPLEMENTATION_STAGES.md` (repo root) — supersedes `PROJECT_SPEC.md` §18's
  phase list. Six stages, each ending in a Verify checklist that must pass
  against a real deployment (not just "the code looks right") before the next
  stage starts. **Do not build ahead of the current stage** — if a stage
  doesn't call for a table, tool, or graph node yet, it doesn't exist yet in
  the repo, even if a later stage's need is obvious.
- `project/` — the actual deployable app (`api/`, `agent/`, `tools/`,
  `services/`, `supabase/`, `tests/`, `requirements.txt`, `vercel.json`),
  per `PROJECT_SPEC.md` §3. `.agents/` sits alongside it at repo root, not
  inside it — same relationship the original `.github/` had to `project/`.

**The database schema will live in `project/supabase/migrations/`** once
Stage 2 creates it — do not redesign it from the ASCII diagrams in
`PROJECT_SPEC.md` §2, and don't create it early (Stage 1 has no Supabase at
all). When it exists, read `project/supabase/README.md` before writing any
code that queries Supabase — it explains the session-variable RLS pattern
(`app.current_user_id`, `app.current_sender_hash`) that every one of those
queries depends on. A connection that never calls `bind_request_context()`
silently returns zero rows rather than an obvious error. That README isn't
written yet either — it's a Stage 2 deliverable, not something to invent
ahead of time.

## Git workflow — always follow

These two rules apply for the whole life of this repo, independent of
which stage is being built:

1. **Always commit changes to the `main` branch on GitHub.** Don't create
   or work out of feature/topic branches for this project — commit
   directly to `main`. (`.agents/hooks.json` denies `git checkout -b` /
   `git switch -c` as a backstop — see `deny_destructive_commands.py`.)
2. **Never commit the `scaffold/` folder.** It's a local
   authoring/staging directory, not part of the shipped repo — the
   actual deployable app lives in `project/`, plus `.agents/` and the
   root `*.md` files sit alongside it. `scaffold/` is git-ignored at the
   repo root (see `.gitignore`) and `deny_destructive_commands.py` also
   blocks `git add`/`git commit` invocations that explicitly name it, as
   a second layer in case the `.gitignore` entry is ever removed.

## Ownership principle (PROJECT_SPEC.md §19)

Keep this true at every layer you build:

```
Supabase business tables      -> What is true
LangGraph state + checkpoints -> What is currently happening
Supabase agent audit tables   -> What permanently happened
LangSmith                     -> Why the agent behaved that way, and how well
Vercel                        -> Where each HTTP execution runs
```

## Non-negotiable invariants

These hold regardless of which file or subagent is active. If a task seems
to require violating one of these, stop and flag it instead of proceeding.

1. **Instructions are not a security boundary.** Every permission check,
   validation rule, and verification step must be enforced in deterministic
   code (`services/authorization.py`, `services/verification.py`, tool input
   validation) — never solely by prompting the LLM not to do something.
2. **No write without read-back verification.** Any code path that inserts
   or updates a row must read it back by ID and compare canonical values
   before reporting success. See `.agents/skills/verification-envelope/`.
3. **No approval accepted on trust alone.** Approval handling must check
   sender identity, role, project-level approval permission, a valid
   unexpired `approval_id`, and a payload-hash match — not just "did a
   WhatsApp reply arrive." See `.agents/skills/whatsapp-approval-flow/`.
4. **Every exposed Supabase table needs RLS + grants**, and every business
   query must filter explicitly by `project_id`. The `service_role` key
   never leaves server-side code and never appears in LangGraph state,
   prompts, or LangSmith traces.
5. **No secrets in LangGraph checkpoint state or LangSmith payloads.**
   Checkpoints are persisted to Postgres; treat that state as semi-public
   within the system.
6. **Respect the bounded-execution limits** (`MAX_AGENT_STEPS`,
   `MAX_TRANSIENT_RETRIES`, `MAX_REPLANS`, `MAX_TOOL_CALLS_PER_RUN`) in any
   code touching the graph's retry/replan logic.

## Directory-scoped rules

Antigravity doesn't glob-match rule files to paths the way some other tools
do, so treat this table as your own routing table — open the relevant file
before editing in that area:

| Editing...                                                              | Read...                          |
|---------------------------------------------------------------------------|-----------------------------------|
| `project/supabase/**`, `project/services/database.py`, `project/tools/**`, any `*migration*.sql` | `.agents/rules/database.md` |
| `project/agent/**`                                                       | `.agents/rules/langgraph.md`      |
| `project/services/authorization.py`, `project/services/approvals.py`, `project/services/verification.py`, `project/services/database.py` | `.agents/rules/security.md` |
| `project/tools/**`                                                       | `.agents/rules/tools.md`          |

## Subagents

Two custom subagents are defined under `.agents/agents/`:

- `build-orchestrator` — implements `IMPLEMENTATION_STAGES.md` stage by
  stage. Treat this as the primary driver for the build.
- `reviewer` — read-only checkpoint review (write-path verification +
  security), invoked manually at 3 fixed points: end of Stage 2, end of
  Stage 5, end of Stage 6. Not per-edit.

## Skills

`.agents/skills/` holds four reusable patterns, loaded automatically when
relevant: `idempotency-key`, `supabase-rls`, `verification-envelope`,
`whatsapp-approval-flow`.

## Hooks

`.agents/hooks.json` wires deterministic guardrails (deny destructive
commands, block `.env` edits, run scoped tests, run `vercel build`, enforce
a clean subagent review) into the agent loop. See
`.agents/hooks/README.md` for the mapping from the original Copilot hook
set and what changed moving to Antigravity's hook model.

## Model / cost economy

Antigravity lets you pick a model per subagent (see each `agent.md`'s
frontmatter) and per interactive session. As a rough default: do mechanical
work (migrations from spec, boilerplate tool scaffolding, docstrings, test
stubs) on a cheaper/faster model; reserve a stronger model for the genuinely
hard parts — LangGraph routing/correction logic (§9), the approval-forgery
checklist (§11), and RLS policy design (§13). Check which model a subagent
or session is on before starting a stage rather than defaulting to the
strongest one everywhere.

## Testing preference

Don't reach for new pytest files as the default way to check work. Prefer,
in order:
1. `vercel build` after a batch of related edits under `api/`, `tools/`,
   `agent/`, `services/`, or `vercel.json` (wired as a hook — see below).
2. `vercel dev` + `tests/smoke_test.sh` once a stage is functionally
   complete.
3. A real `vercel deploy` preview only when you need actual function logs,
   or at the very end of a stage's Verify checklist.
Reserve pytest for pure functions in `services/verification.py` and
`services/authorization.py` that are awkward to check via a running server.
