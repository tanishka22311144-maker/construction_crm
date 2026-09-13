# Repo-wide Copilot instructions

This repo has two separate instruction layers — don't confuse them:

- `agent/instructions.md` — the RUNTIME system prompt loaded by the deployed
  LangGraph agent on every WhatsApp request. Edit it only when you intend to
  change agent behavior in production, and remember changes take effect only
  after the next Vercel deploy.
- Everything under `.github/` (this file, `.github/instructions/`,
  `.github/agents/`, `.github/skills/`, `.github/hooks/`) — guidance for
  YOU, GitHub Copilot, while writing the code that implements that spec.

The full build spec is `PROJECT_SPEC.md` at the repo root — it's the
reference for the end-state design (schema, tools, full graph, approval
checklist). For BUILD ORDER, use `IMPLEMENTATION_STAGES.md` instead — it
supersedes PROJECT_SPEC.md §18's phase list with a 6-stage sequence where
the bot is real and testable over actual WhatsApp messages after every
stage, not just at the end. Do not build ahead of the current stage.

**The database schema already exists** in `supabase/migrations/` — do not
redesign it from the ASCII diagrams in `PROJECT_SPEC.md` §2. Read
`supabase/README.md` before writing ANY code that queries Supabase
(`services/database.py`, every file under `tools/`, and any graph node
that reads/writes business data) — it explains a session-variable RLS
pattern (`app.current_user_id`, `app.current_sender_hash`) that every one
of those queries depends on, and it isn't optional context: a connection
that never calls `bind_request_context()` will have every query silently
return zero rows rather than an obvious error.

## Non-negotiable invariants

These hold regardless of which file, agent, or subagent is active. If a
task seems to require violating one of these, stop and flag it instead of
proceeding:

1. **Instructions are not a security boundary.** Every permission check,
   validation rule, and verification step must be enforced in deterministic
   code (`services/authorization.py`, `services/verification.py`, tool
   input validation) — never solely by prompting the LLM not to do
   something.
2. **No write without read-back verification.** Any code path that inserts
   or updates a row must read it back by ID and compare canonical values
   before reporting success. See `.github/skills/verification-envelope/`.
3. **No approval accepted on trust alone.** Approval handling must check
   sender identity, role, project-level approval permission, a valid
   unexpired `approval_id`, and a payload-hash match — not just "did a
   WhatsApp reply arrive." See `.github/skills/whatsapp-approval-flow/`.
4. **Every exposed Supabase table needs RLS + grants**, and every business
   query must filter explicitly by `project_id`. The `service_role` key
   never leaves server-side code and never appears in LangGraph state,
   prompts, or LangSmith traces.
5. **No secrets in LangGraph checkpoint state or LangSmith payloads.**
   Checkpoints are persisted to Postgres; treat that state as semi-public
   within the system.
6. **Respect the bounded-execution limits** (`MAX_AGENT_STEPS`,
   `MAX_TRANSIENT_RETRIES`, `MAX_REPLANS`, `MAX_TOOL_CALLS_PER_RUN`) in any
   code touching the graph's retry/replan logic — a Vercel function has a
   hard duration ceiling and nothing should assume otherwise.

For anything touching a specific directory, more detailed instructions
live under `.github/instructions/` and apply automatically based on path.
These are free to use — they're loaded as context, not a chat turn.

## Working within a limited Copilot plan

You're on GitHub Copilot Student — 300 premium requests/month, same
allowance as Pro, reset monthly with no rollover. That's workable for this
build, but a 6-stage project (see `IMPLEMENTATION_STAGES.md`) with many
files can burn through 300 fast if every edit turns into its own
agent-mode turn. Rough budget to aim for:

- ~40–50 premium requests per stage (6 stages), leaving headroom for
  re-work and the occasional stronger-model escalation.
- The 3 `reviewer` checkpoints (end of Stage 2, 5, 6 — see the
  orchestrator's file) are a small, fixed cost against that budget —
  don't add more of them, but don't be afraid to use the ones you have;
  they're cheap relative to the generation work.
- Everything routed through hooks (`vercel build`, scoped pytest,
  `tests/smoke_test.sh`) costs 0 against the 300 — lean on those as your
  default feedback loop, and treat a `reviewer` call or a fresh agent-mode
  turn as the more expensive option to reach for deliberately, not by
  default.
- Included/base models (used in day-to-day Chat, and by `reviewer`) don't
  draw from the 300 at all on paid plans — only premium-model turns and
  agent-mode/cloud-agent steps do. Do the mechanical work in a base-model
  chat where you can, and switch to agent mode (which does consume
  requests) only when you actually need it to read/write files across the
  repo.
