<!-- Applies to: project/agent/** -->

# LangGraph rules

> Stage 1 (`IMPLEMENTATION_STAGES.md`) shipped `agent/graph.py` as a
> plain Python for-loop over node functions, not a `StateGraph` — an
> explicitly scoped, temporary exception to every rule below, allowed
> only because a two-node, branch-free pipeline has no real edges to
> get wrong yet. From Stage 2 onward (see that stage's Build section)
> `agent/graph.py` is a real `langgraph.graph.StateGraph`, and every
> rule below applies to it in full.

- `AgentState` fields are fixed per `PROJECT_SPEC.md` §4 — extend it only by
  adding new optional keys, never by repurposing an existing key for a
  different meaning.
- Never put secrets, tokens, or raw Supabase keys into state — it is
  persisted by the Postgres checkpointer and is not a secure store.
- Follow the node graph in `PROJECT_SPEC.md` §5 exactly, including which
  failures route to `correction` vs `safe_failure` vs `ask_user`. Don't
  collapse `validate_tool_result` and `verify_operation` into one node —
  they check different things (structural validity vs business-value
  correctness) and both must independently pass.
- `request_approval` must save a checkpoint and let the function exit — it
  must never `sleep`, poll, or otherwise block waiting for a human response
  inside the invocation. Resumption happens via a later webhook calling
  `Command(resume=...)` against the same `thread_id`. See PROJECT_SPEC.md
  §17 for the full request lifecycle this guarantees.
- Don't collapse `create_plan`/`validate_plan`/`resolve_project` or the
  approval/retry routing (PROJECT_SPEC.md §5, §9) into fewer nodes than the
  graph diagram shows, even once they all exist — each failure branch
  (`correction`, `safe_failure`, `ask_user`, `replan`) needs to be
  independently reachable and independently testable.
- Use `InMemorySaver` / `MemorySaver` only in local tests. Any code path
  reachable in `api/index.py` must use the Postgres checkpointer.
- Enforce `MAX_AGENT_STEPS`, `MAX_TRANSIENT_RETRIES`, `MAX_REPLANS`,
  `MAX_TOOL_CALLS_PER_RUN` as hard stops with a `safe_failure` exit, not
  soft warnings.
- Never answer a business question (project status, record contents, field
  definitions) from `messages`/checkpoint state or `chat_sessions` history —
  always re-read from Supabase business tables in
  `generate_grounded_response`.
