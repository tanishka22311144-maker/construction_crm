# Implementation stages (MINT framework)

> **Current Implementation Progress:**
> - Stage 1: Complete and verified.
> - Stage 2: Complete and verified (Migrated to real `StateGraph`, read-only tool `read_project_data` works, database connectivity and WhatsApp sender identity resolved).
> - Stage 3: Next up — Add continuous evaluation (Validation, evaluation nodes, retry/replan logic, LangSmith).
>
> Work resumes at **Stage 3 Build**.
>
> One thing carries forward that is *not* business as usual: Stage 1's
> `agent/graph.py` is a plain Python for-loop over node functions
> (`run_agent()`), not a real LangGraph graph — that was a deliberate,
> scoped-down shortcut for a two-node, branch-free pipeline (see the
> Stage 1 Build note below). `PROJECT_SPEC.md` §4–§5 and
> `.agents/rules/langgraph.md` both assume an actual
> `langgraph.graph.StateGraph`, and Stage 2 is where that stops being
> optional: this stage introduces the first conditional branch
> (`check_permission`: denied vs. allowed), which the Stage 1 runner has
> no way to express. **Stage 2's Build section below starts with
> migrating `agent/graph.py` onto a real `StateGraph` before anything
> else in this stage is added** — every stage from here on builds nodes
> and edges into that graph, not into the old runner.

This supersedes the Phase 1–6 build order in `PROJECT_SPEC.md` §18.
`PROJECT_SPEC.md` is still the reference for the *end-state* design — full
schema, all four tools, the complete graph, the approval checklist. This
file is the reference for *sequencing*: what subset of that end state to
build first, so the bot is real and testable after every stage instead of
only at the very end.

Rule for every stage: don't build ahead of it. If a stage doesn't call for
a table, a tool, or a graph node yet, it doesn't exist yet in the repo —
resist pulling forward something that "will be needed eventually." Stage
1 in particular is meant to be almost embarrassingly small. \
**EVERYTIME YOU MAKE CHANGES WRITE IT HERE AS THE CURRENT STAGE IMPLEMENTATION
PROGRESS AT THE VERY START OF `IMPLEMENTAION_STAGES.md`**

Each stage ends with a **Verify** section. Do not start the next stage
until every item in the current stage's Verify section actually passes
against a real deployment — not just "the code looks right." A stage that
only compiles is not a completed stage.

---

## Stage 1 — Basic prompt ✅ COMPLETE

> Message comes in → Agent answers. Do this working, nothing else.

**Build**

- `api/index.py`: Meta webhook handler — GET verification handshake
  (echo `hub.challenge` when `hub.verify_token` matches), POST handler
  that extracts the text message.
- `agent/state.py`: the full `AgentState` from PROJECT_SPEC.md §4, even
  though most fields are unused yet — the shape doesn't change stage to
  stage, only which nodes populate it.
- `agent/graph.py`, `agent/nodes.py`: exactly two real nodes —
  `receive_request` → `generate_response` (a single LLM call using
  `agent/instructions.md` as system prompt) → `send_whatsapp_response`.
  Every other node named in PROJECT_SPEC.md §5 does not exist yet.
  **Deliberate Stage 1-only shortcut:** wire these three as a plain
  Python function calling the node functions in sequence, not a real
  `langgraph.graph.StateGraph` — with no branching yet, a graph object
  buys nothing at this stage. This is scoped to Stage 1 only: flag it
  with a `# TODO(stage-2)` comment, and see Stage 2's Build section
  below, which replaces it with a real `StateGraph` the moment the first
  branch (`check_permission`) exists.
- Checkpointer: `MemorySaver`, explicitly temporary — flag this with a
  `# TODO(stage-4)` comment, since `.agents/rules/langgraph.md`
  normally forbids `MemorySaver` outside local tests. It's allowed here
  only because there is no state worth persisting yet.
- No Supabase. No tools. No permission checks. No dedup.

**Known, accepted gap at this stage:** Meta may redeliver a webhook, and
with no `processed_messages` table yet, a redelivered message gets a
second reply. That's fine for Stage 1 — it's closed in Stage 4. Don't fix
it early; it'd mean building `processed_messages` out of order.

**Verify** — all items below have passed against a real deployment; Stage 1 is closed.

- [x] `vercel build` succeeds locally.
- [x] `vercel dev` runs; `tests/smoke_test.sh` (pointed at a generic
      message, not a business query yet) gets back a non-error reply.
- [x] `vercel deploy` to a preview URL; confirm the deployment is live
      (`vercel ls` / the returned URL responds).
- [x] In Meta's App Dashboard, set the webhook URL to the preview URL +
      your verify token; confirm Meta's verification handshake succeeds
      (green checkmark in the dashboard, not just "no error" in your logs).
- [x] From a real phone on Meta's test-recipient list, send an actual
      WhatsApp message. Confirm a reply arrives in the chat within a few
      seconds.
- [x] `vercel logs <deployment-url>` shows the request with no
      unhandled exceptions.
- [x] Send the same message twice in a row; confirm you get two replies
      (this is the accepted gap above — verifying it's present, not
      absent, tells you Stage 4 actually fixed something real later).

---

## Stage 2 — Add a tool use (read-only)

> Add `read_project_data`.

**Build**

- **Migrate `agent/graph.py` onto a real `langgraph.graph.StateGraph`
  before adding anything else this stage.** Stage 1's `run_agent()` was
  a plain for-loop by design (see Stage 1's note above) — that stops
  being sufficient the moment this stage introduces its first branch:
  `check_permission` denied → `safe_failure` vs. allowed →
  `execute_tool` (PROJECT_SPEC.md §5). Concretely:
  - Build the graph as `StateGraph(AgentState)` (`AgentState` from
    `agent/state.py`, unchanged), registering each node from
    PROJECT_SPEC.md §5 that exists as of this stage via `add_node`.
  - Use `add_edge` for straight-line transitions and
    `add_conditional_edges` for the `check_permission` branch — do not
    simulate the branch with an `if` inside a single node function; it
    must be a real edge in the compiled graph, per
    `.agents/rules/langgraph.md`'s rule against collapsing distinct
    failure branches into fewer nodes than the graph diagram shows.
  - Compile with `.compile(checkpointer=MemorySaver())` — still
    `MemorySaver` this stage (the `# TODO(stage-4)` from Stage 1 still
    applies; only the graph construction around it changes, not the
    checkpointer), and give every invocation a `thread_id` via
    `config={"configurable": {"thread_id": state["thread_id"]}}`.
  - Export the compiled graph object (e.g. `graph = builder.compile(...)`)
    from `agent/graph.py` in place of the old `run_agent` function, and
    update `api/index.py` to call `graph.invoke(state, config=...)`
    instead of importing `run_agent`.
  - `agent/nodes.py` node functions themselves don't need to change
    shape — they still take and return state — only how they're wired
    together changes.
- Run migrations `20260101000100` through `20260101000600`
  (`projects` → `user_project_access`) from `supabase/migrations/`.
  `chat_sessions` gets created as part of this batch too — that's fine,
  it stays empty and unused until Stage 4.
- `services/database.py`: connection setup + `bind_request_context()`
  per `supabase/README.md` — required from this stage on, since
  `project_records` reads are RLS-gated.
- `services/authorization.py`: `authorize()`, checking
  `user_project_access.can_read` only (write permissions come in Stage 5).
- `tools/schemas.py`, `tools/read_project_data.py`: implement per
  `.agents/rules/tools.md`.
- Graph nodes added: `load_instructions` (loads `agent/instructions.md`
  fresh — was hardcoded inline in Stage 1), `load_identity_and_memory`
  (identity lookup only, no chat history yet — that's Stage 4),
  `check_permission`, `execute_tool`. Keep `understand_request` simple:
  "is this a read request or not," not the full plan/validate machinery
  yet — that's Stage 3.

**Verify**

- [x] Seed one row each in `projects`, `agent_users` (hash matching your
      own test WhatsApp number), and `user_project_access` (`can_read =
      true`), plus a couple of `project_records` rows, directly via SQL
      or Supabase Studio.
- [x] As the `postgres`/admin role, confirm the seeded rows exist.
- [x] As `app_backend` with no session variable set, confirm a `select`
      on `project_records` returns 0 rows (RLS is actually active — reuse
      the `set role app_backend; select count(*)...` check from
      `supabase/README.md`).
- [x] As `app_backend` with `app.current_user_id` set to your seeded
      user, confirm the same query returns the expected rows.
- [x] Update `tests/smoke_test.sh` to send "Show expenses for
      \<your seeded project name\>" and assert the response text actually
      contains the seeded data (not a hallucinated-sounding generic
      answer).
- [x] `vercel dev` + smoke test passes; then `vercel deploy` preview;
      then a real WhatsApp message asking about the seeded project — the
      reply must reflect real DB content.
- [x] Send a WhatsApp message asking about a project that doesn't exist,
      or a WhatsApp number not in `agent_users` — confirm a clear
      "not found" / "not registered" reply, not a stack trace or a
      hallucinated answer.
- [x] Confirm `agent/graph.py` now builds and compiles a real
      `StateGraph` (e.g. it exposes a compiled `graph` object, and
      `run_agent`/a manual node-dispatch loop no longer exists anywhere
      in the diff) rather than carrying Stage 1's for-loop forward.
- [x] Temporarily flip your seeded `user_project_access.can_read` to
      `false` and re-send the same project query; confirm the reply is
      a clear denial and that this happened via the `check_permission`
      conditional edge actually routing to a different node — not an
      `if` statement bolted inside one node — by checking that a denied
      run's trace only visits `safe_failure`, not `execute_tool`.

---

## Stage 3 — Add continuous evaluation

> The agent checks its own tool results before trusting them, and
> corrects itself within bounds instead of either looping forever or
> silently returning something wrong.

**Build**

- `services/verification.py`: structural result validation for reads —
  bounded row count, well-formed result shape, no hidden error (the read
  side of PROJECT_SPEC.md §7 Layers 2, 3, 5, 7 — Layer 6, post-write
  read-back, doesn't apply yet since there are no writes until Stage 5).
- Graph nodes added: `create_plan`, `validate_plan`, `resolve_project`
  (no-match / multiple-match → `ask_user`, not a guess), `validate_tool_result`,
  `evaluate_goal`, plus the retry/replan routing from PROJECT_SPEC.md §9
  with `MAX_TRANSIENT_RETRIES` / `MAX_REPLANS` / `MAX_AGENT_STEPS` enforced
  as hard stops.
- LangSmith: set the four env vars from PROJECT_SPEC.md §14, wire
  `langgraph_config` with `thread_id`/`run_id`/`user_hash` metadata into
  every graph invocation.
- Add 2–3 rows from PROJECT_SPEC.md §16's dataset examples (the
  read-only ones) as your first LangSmith eval set.

**Verify**

- [ ] Send a misspelled or ambiguous project name over WhatsApp; confirm
      the agent asks which project you meant instead of guessing one.
- [ ] Ask for something outside the four tools (e.g., "delete this
      project"); confirm a clear "not supported" reply, not an invented
      tool call.
- [ ] Open the LangSmith project dashboard; confirm a trace exists for a
      recent request showing separate runs for plan creation, tool
      execution, and result validation as distinct steps, not one opaque
      blob.
- [ ] Temporarily break connectivity (e.g., point `SUPABASE_URL` at a
      wrong host in a preview deployment's env vars) and send a request;
      confirm the agent retries a bounded number of times (visible in
      `vercel logs` as repeated attempts, not an infinite loop) and then
      fails with a clear message — then revert the env var.
- [ ] Run your LangSmith eval set once; confirm all read-path examples
      pass before moving on.

---

## Stage 4 — Add state and memory

> Multi-turn conversations survive across separate Vercel invocations,
> and every run leaves a durable trail.

**Build**

- Switch the checkpointer from `MemorySaver` to
  `langgraph-checkpoint-postgres`, pointed at the same Supabase Postgres
  instance; run its `setup()` once (see `supabase/README.md`'s note that
  its tables are LangGraph-owned, not part of the numbered migrations).
- Run migrations `20260101000700` (`agent_runs`, `agent_events`) and
  `20260101000900` (`processed_messages`).
- Wire `load_identity_and_memory` to also load the last 6–10
  `chat_sessions` rows for this user.
- Add the idempotency dedup check (per
  `.agents/skills/idempotency-key/SKILL.md`) at the very top of
  `api/index.py`, before anything else runs — this is what finally closes
  the Stage 1 double-reply gap.
- Log every node transition as an `agent_events` row (per
  PROJECT_SPEC.md §15) from this stage forward.

**Verify**

- [ ] Send a 2-message conversation over real WhatsApp — e.g. "Add a
      fuel expense" (agent should ask for the amount, per the example in
      PROJECT_SPEC.md §12) then "₹2500" — confirm the second message
      completes the first without you having to repeat context.
      (Full write execution isn't wired until Stage 5 — it's fine if it
      still can't actually insert yet; what you're proving here is that
      the *conversation* carries state, via `thread_id`, across two
      separate messages/invocations.)
- [ ] Restart `vercel dev` (or trigger a cold start on a preview
      deployment) in the middle of a multi-turn conversation and send the
      next message; confirm it resumes correctly — this is the proof the
      checkpoint is durable in Postgres, not just held in the process's
      memory.
- [ ] Using `curl`, resend the exact same synthetic webhook payload twice
      (same `message_id`); confirm only one reply is sent, and check
      `processed_messages` to confirm the second delivery was recognized
      as a duplicate rather than reprocessed.
- [ ] Query `agent_events` in Supabase for a recent `run_id`; confirm a
      full, ordered sequence of node-transition rows exists for it.

---

## Stage 5 — Add more tools (write)

> `add_project_row`, `create_project_field`, `create_project`.

**Build**

- `tools/add_project_row.py`, `create_project_field.py`,
  `create_project.py`, each following the write-tool sequence in
  `.agents/rules/tools.md` and the envelope +
  read-back pattern in `.agents/skills/verification-envelope/SKILL.md`.
- Full write-path verification: PROJECT_SPEC.md §7 Layer 6 (post-write
  read-back) now applies.
- Idempotency key check before every insert (per the skill), reusing the
  dedup infrastructure from Stage 4.
- **Ship `add_project_row` for real use this stage.** `create_project_field`
  and `create_project` are code-complete this stage but stay
  feature-flagged off (or restricted to your own admin test account) —
  both are mandatory-approval operations per PROJECT_SPEC.md §6, and
  there's no approval mechanism to gate them until Stage 6. Shipping a
  mandatory-approval tool with no approval path would be a real gap, not
  a shortcut.

**Verify**

- [ ] Send "Add a fuel expense of 2500 to \<project\>" over WhatsApp;
      query `project_records` directly in Supabase and confirm a row
      exists with the correct values.
- [ ] Send the exact same message twice within a few seconds; confirm
      only one row is inserted and the agent's second reply reflects that
      (e.g., "already recorded") rather than creating a duplicate.
- [ ] Send a message with an invalid value (letters where an amount is
      expected); confirm the agent reports the validation failure and
      confirm via SQL that nothing was written.
- [ ] Query `agent_events` for this write's `run_id`; confirm a
      `VERIFICATION_PASSED` event with populated `output_json` (matched
      fields, no mismatches).
- [ ] Confirm (by testing as a non-admin account) that asking to add a
      field or create a project either does nothing or clearly says
      "not available yet" — it must not silently execute without
      approval.

---

## Stage 6 — Add human in loop

> Unlock `create_project_field` and `create_project` behind a real
> WhatsApp-only approval flow.

**Build**

- Run migration `20260101000800` (`pending_approvals`).
- `services/approvals.py`, implementing the full checklist in
  `.agents/skills/whatsapp-approval-flow/SKILL.md` and PROJECT_SPEC.md
  §11 — role match, project-level `can_approve_*`, unexpired
  `approval_id`, `approval_token_hash` match, payload-hash match.
- Graph nodes: `request_approval` (interrupt + checkpoint + exit, never
  block), `resume_after_approval` (approve / edit-then-revalidate /
  reject / expired routing).
- Unlock `create_project_field` and `create_project` for real users now
  that the approval gate actually exists.

**Verify**

- [ ] As a low-privilege user, request a field addition; confirm the
      approval-request WhatsApp message is sent to the *approver's*
      number, not back to the requester.
- [ ] As the approver, reply `APPROVE APR-XXXX`; confirm the field
      definition is actually inserted, and the *original requester* (not
      the approver) gets a confirmation — proving the paused thread
      resumed correctly via `thread_id`, not as a brand-new conversation.
- [ ] Reply `REJECT APR-XXXX <reason>` on a different request; confirm
      nothing is created and the requester is notified with the reason.
- [ ] As an active user without the matching approver role, try to
      approve a pending request; confirm it's rejected with
      `invalid_approval_context`, not silently accepted.
- [ ] Try approving with a stale or already-decided `approval_id`;
      confirm it's rejected rather than re-executed.
- [ ] Check `vercel logs` for the function invocation that sent the
      approval request: confirm its duration is short (it saved a
      checkpoint and exited), and that a *separate*, later invocation —
      triggered by the approver's reply — is what actually resumes and
      completes the operation. This is the concrete proof that
      PROJECT_SPEC.md §17's "never block inside a Vercel function" rule
      is genuinely satisfied, not just documented.
- [ ] Run the full LangSmith eval set from PROJECT_SPEC.md §16,
      including the write and approval-required examples, end to end.

---

## After Stage 6

At this point every table, tool, and node in `PROJECT_SPEC.md` exists and
has been exercised over real WhatsApp messages. What's left is what
PROJECT_SPEC.md §18 originally called "Phase 6: Deployment" —
production Vercel config, environment variables, function duration
tuning, and a final production deploy — which is now just hardening an
already-verified system rather than a leap of faith.
