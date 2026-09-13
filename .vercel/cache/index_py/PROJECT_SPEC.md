# Build Instructions — WhatsApp Construction Agent

> **Build order lives in `IMPLEMENTATION_STAGES.md`, not §19 below.**
> This file is the end-state reference — full schema, all four tools, the
> complete graph, the approval checklist. `IMPLEMENTATION_STAGES.md`
> sequences that into 6 stages (basic prompt → read tool → evaluation →
> state/memory → write tools → human-in-loop), each one shippable and
> testable over real WhatsApp messages on its own. §19's phase list below
> is kept for historical/design-rationale reference but is superseded for
> actual build sequencing.


You are the coding agent responsible for implementing this project end to end.
This file is both your build spec and (once placed at `agent/instructions.md`)
the system instruction loaded into the LangGraph agent at runtime. Read it
fully before writing any code. Follow the phases in order — later phases
depend on tables, tools, and state defined in earlier ones.

Two deliberate simplifications from the reference architecture, in effect
everywhere below:

1. **No separate user-verification step.** There is no OTP, challenge, or
   identity-proofing flow. A WhatsApp sender is identified purely by hashing
   their WhatsApp number and matching it against `agent_users`. If the hash
   matches an active row, the sender *is* that user for the rest of the run.
   There is no "verify identity" node in the graph — identity resolution and
   lookup happen in a single step (`load_identity_and_memory`), and if there
   is no match, the run fails safely with a "not registered" response.
   Permission and role checks (`user_project_access`, `agent_users.role`)
   still apply in full — only the *authentication* step is removed, not
   authorization.
2. **WhatsApp is the only approval UI.** There is no web dashboard, email
   link, or separate approval channel. Approval requests are sent as
   WhatsApp messages to the approver's registered number, and the approver
   responds with a WhatsApp message. All approval-flow design below assumes
   this constraint.

---

## 1. Target architecture

```
WhatsApp User / Client
        │
        ▼
Meta WhatsApp Cloud API
        │
        ▼
Vercel Python Function (FastAPI)
        │
        ├── Validate Meta webhook payload
        ├── Deduplicate message_id
        ├── Mask PII before any logging
        └── Resolve sender → agent_users (no separate auth step)
        │
        ▼
LangGraph Agent
        │
        ├── Load instructions.md
        ├── Load checkpoint (Postgres)
        ├── Load conversation memory (chat_sessions)
        ├── Understand request → plan → validate plan
        ├── Check permission → classify risk
        ├── Request approval via WhatsApp (interrupt, if needed)
        ├── Execute tool → read back → verify
        ├── Retry / correct / replan within bounds
        └── Generate grounded response
        │
        ├──────────────────────┐
        ▼                      ▼
   Supabase                LangSmith
        │                      │
        ├── Business data      ├── LLM traces
        ├── Permissions        ├── Tool-call traces
        ├── Checkpoints        ├── Node transitions
        ├── Agent audit        ├── Latency / errors
        └── Approvals          └── Evaluations
        │
        ▼
Meta WhatsApp API → User receives response
```

Constraints to respect throughout:

- Vercel hosts one Python function per `vercel.json`; all execution must
  finish within the configured `maxDuration`. Nothing should ever block
  inside the function waiting on a human — see §11.
- LangGraph owns state machine, checkpoints, and interrupts.
- LangSmith is observability/evaluation only — it is not the audit system
  of record. Supabase is.
- An instruction file (this one) is never a security boundary. Deterministic
  backend authorization and validation code must independently prevent
  everything this file tells the model not to do.

---

## 2. Database schema (Supabase / Postgres)

Build these tables in the order given in Phase 1 (§13). Enable RLS and
grants on every table before shipping anything past a local/dev environment.

### Core business tables

```
projects
├── id
├── project_name
├── project_code
├── location
├── status
├── created_by
└── created_at

project_records
├── id
├── project_id
├── record_type
├── record_date
├── title
├── description
├── amount
├── unit
├── data JSONB
├── created_by
├── created_at
└── updated_at

project_field_definitions
├── id
├── project_id
├── record_type
├── field_name
├── field_type
├── required
├── default_value
├── validation_rules JSONB
├── created_by
└── created_at

chat_sessions
├── id
├── user_id
├── user_message
├── assistant_reply
├── run_id
└── created_at
```

Migration mapping from any legacy tables:

| Old table | New location |
|---|---|
| `daily_logs` | `project_records`, `record_type = daily_log` |
| `expenses` | `project_records`, `record_type = expense` |
| `equipment_logs` | `project_records`, `record_type = equipment_log` |
| `project_attributes` | `project_records` or `project_field_definitions` |
| `projects` | `projects` |
| `chat_sessions` | `chat_sessions` |

### Identity and permission tables

```
agent_users
├── id
├── whatsapp_sender_hash      -- sha256 of the WhatsApp number; this IS the identity
├── display_name
├── role
├── is_active
└── created_at

user_project_access
├── id
├── user_id
├── project_id
├── can_read
├── can_add_rows
├── can_propose_fields
├── can_approve_fields
├── can_propose_projects
├── can_approve_projects
└── created_at
```

There is no separate `verified` or `auth_token` column on `agent_users` —
by design, matching `whatsapp_sender_hash` to an active row is the entire
authentication step (see §11 for how this interacts with approvals).

### Durable agent / audit tables

```
agent_runs
├── id
├── thread_id
├── user_id
├── message_id
├── status
├── intent
├── current_node
├── retry_count
├── started_at
├── completed_at
├── final_response
├── error_code
└── error_message

agent_events
├── id
├── run_id
├── sequence_number
├── event_type
├── status
├── node_name
├── tool_name
├── input_json
├── output_json
├── decision_json
├── error_json
├── duration_ms
└── created_at

pending_approvals
├── id
├── run_id
├── thread_id
├── requested_by
├── required_approver_role
├── operation
├── proposed_payload
├── status
├── approval_token_hash        -- see §11: this is the sole extra check, generated server-side
├── requested_at
├── expires_at
├── decided_by
├── decision
├── decision_reason
└── decided_at

processed_messages
├── message_id
├── sender_hash
├── status
├── run_id
└── processed_at
```

---

## 3. Project structure

```
project/
├── api/
│   └── index.py
├── agent/
│   ├── instructions.md      -- this file, copied here verbatim
│   ├── graph.py
│   ├── state.py
│   ├── nodes.py
│   ├── routing.py
│   └── prompts.py
├── tools/
│   ├── schemas.py
│   ├── read_project_data.py
│   ├── add_project_row.py
│   ├── create_project_field.py
│   └── create_project.py
├── services/
│   ├── authorization.py
│   ├── verification.py
│   ├── audit.py
│   ├── approvals.py
│   └── database.py
├── supabase/
│   ├── README.md            -- session-variable RLS pattern; read before
│   │                           writing services/database.py or any tool
│   └── migrations/          -- the actual schema; see §2 for the design
│                                this was derived from
├── tests/
│   ├── services/            -- unit tests, matched 1:1 to services/*.py
│   └── smoke_test.sh        -- end-to-end check via `vercel dev`
├── requirements.txt
└── vercel.json
```

`.github/` also exists at the repo root alongside `project/` above, but it
holds GitHub Copilot build tooling (instructions, agents, skills, hooks)
rather than anything the deployed application imports or ships — treat it
as a separate concern from the runtime structure listed here.
```

Loading mechanics: the agent does **not** auto-discover `instructions.md`.
Load it explicitly once per function cold start and pass it as the system
instruction on every model call:

```python
from pathlib import Path

INSTRUCTIONS_PATH = Path(__file__).resolve().parent / "instructions.md"
AGENT_INSTRUCTIONS = INSTRUCTIONS_PATH.read_text(encoding="utf-8")
```

Changes to this file only take effect after the next Vercel deployment.

Instruction precedence (highest to lowest):

1. Backend authorization and database constraints
2. Tool validation logic
3. LangGraph routing rules
4. This file
5. Current user request

---

## 4. LangGraph state

```python
from typing import TypedDict, Optional
from typing_extensions import Annotated
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # Identity (resolved, not "verified" — see intro)
    run_id: str
    thread_id: str
    user_id: str
    sender_hash: str
    message_id: str

    # Conversation
    messages: Annotated[list, add_messages]
    incoming_message: str

    # Request interpretation
    intent: Optional[str]
    requested_outcome: Optional[str]
    missing_fields: list[str]

    # Project context
    project_id: Optional[str]
    project_name: Optional[str]

    # Plan
    plan: list[dict]
    current_step: int
    selected_tool: Optional[str]
    tool_arguments: dict

    # Security
    risk_level: Optional[str]
    permission_result: dict
    human_approval_required: bool
    approval_id: Optional[str]
    approval_status: Optional[str]

    # Execution
    tool_result: dict
    verification_result: dict

    # Correction control
    retry_count: int
    replan_count: int
    last_error: Optional[dict]

    # Completion
    goal_complete: bool
    final_response: Optional[str]
```

Never put secrets in this state — checkpoint state is persisted to Postgres.

---

## 5. LangGraph flow

```
START
  │
  ▼
receive_request
  │
  ▼
load_instructions
  │
  ▼
load_identity_and_memory        -- hash sender number, look up agent_users, load last N chat_sessions
  │                                (no separate verification node — no match = safe_failure)
  ▼
understand_request
  │
  ├── Domain question
  ├── Write request
  ├── Missing information
  └── Unsupported request
  │
  ▼
create_plan
  │
  ▼
validate_plan
  │
  ├── Invalid plan → correction
  ├── Unsupported tool → safe_failure
  └── Valid plan
  │
  ▼
resolve_project
  │
  ├── No match → ask_user
  ├── Multiple matches → ask_user
  └── Exact match
  │
  ▼
check_permission
  │
  ├── Denied → safe_failure
  └── Allowed
  │
  ▼
classify_risk
  │
  ├── Low → execute_tool
  ├── Medium → conditional approval
  ├── High → mandatory approval
  └── Critical → mandatory admin approval
  │
  ▼
request_approval                -- sends a WhatsApp message to the approver; this is the ONLY UI
  │
  ├── interrupt()
  ├── save checkpoint
  ├── send approval request over WhatsApp
  └── exit Vercel function
  │
  ▼
resume_after_approval            -- resumed by a later WhatsApp webhook from the approver
  │
  ├── Rejected → safe_failure
  ├── Expired → safe_failure
  ├── Edited → revalidate_plan
  └── Approved → execute_tool
  │
  ▼
execute_tool
  │
  ▼
validate_tool_result
  │
  ├── Invalid success response → correction
  ├── Transient error → retry
  └── Structurally valid result
  │
  ▼
read_back
  │
  ▼
verify_operation
  │
  ├── Mismatch → correction
  ├── Record missing → correction
  ├── Permission result wrong → safe_failure
  └── Verified
  │
  ▼
evaluate_goal
  │
  ├── More plan steps → check_permission
  ├── Goal incomplete → replan
  └── Complete
  │
  ▼
generate_grounded_response
  │
  ▼
sanitize_response
  │
  ▼
persist_chat_and_audit
  │
  ▼
send_whatsapp_response
  │
  ▼
END
```

Build every node to return a structured result, e.g.:

```json
{
  "success": true,
  "status": "completed",
  "code": "PROJECT_RESOLVED",
  "data": {},
  "warnings": [],
  "error": null
}
```

---

## 6. Tools

Implement exactly four business tools. The LLM never sees or writes SQL —
every tool resolves names to IDs internally and validates its own inputs.

### Tool 1 — `read_project_data`
Permission: read · Approval: none · Risk: low

Steps: resolve project → check user/project access → load field definitions
→ read records → apply filters → clamp `limit` to 50 → return structured
records.

```json
{
  "project_name": "Pipeline Alpha",
  "record_type": "expense",
  "fields": ["category", "payment_mode", "vendor_or_recipient"],
  "filters": {"record_date_from": "2026-09-01", "record_date_to": "2026-09-02"},
  "limit": 20
}
```

### Tool 2 — `add_project_row`
Permission: write project record · Approval: conditional · Risk: medium

Steps: resolve project → check write permission → load field definitions →
validate each field → apply defaults → insert one `project_records` row →
return record ID → read it back → compare stored values → return verified
result.

```json
{
  "project_name": "Pipeline Alpha",
  "record_type": "expense",
  "record_date": "2026-09-02",
  "title": "Fuel",
  "amount": 2500,
  "unit": "INR",
  "data": {"category": "Fuel", "payment_mode": "UPI", "vendor_or_recipient": "ABC Fuels"}
}
```

Conditional approval rules:

- Daily log → no approval if `can_add_rows`
- Equipment log → no approval if `can_add_rows`
- Expense below configured threshold → no approval (or simple requester
  confirmation, still over WhatsApp)
- Expense above configured threshold → finance approver required over
  WhatsApp

### Tool 3 — `create_project_field`
Permission: propose field · Approval: mandatory · Risk: high

Does **not** alter the physical Postgres table — inserts a governed row
into `project_field_definitions`.

```json
{
  "project_name": "Pipeline Alpha",
  "record_type": "daily_log",
  "field_name": "workers_present",
  "field_type": "integer",
  "required": false,
  "default_value": 0,
  "validation_rules": {"minimum": 0, "maximum": 500},
  "reason": "Track daily workforce availability"
}
```

Steps: validate field name → check duplicate → validate allowed field type
→ validate validation rules → check proposer permission → create approval
request → pause graph → admin approves over WhatsApp → insert field
definition → read it back → verify every property → complete.

### Tool 4 — `create_project`
Permission: propose project · Approval: mandatory · Risk: critical

Creates one `projects` row, default `project_field_definitions` rows,
initial `user_project_access` rows, and audit records. Does not create a
physical table.

```json
{
  "project_name": "Mumbai Metro Phase 2",
  "project_code": "MMP2",
  "location": "Mumbai",
  "status": "Planned",
  "default_record_types": ["daily_log", "expense", "equipment_log"]
}
```

Must be transactional:

```
Begin transaction
    ├── Insert project
    ├── Insert default fields
    ├── Add creator access
    ├── Verify project
    ├── Verify field definitions
    └── Commit
Any failure → Rollback
```

---

## 7. Verification (every layer, every request)

### Layer 1 — Webhook
Valid Meta webhook token, valid payload structure, text message present,
`message_id` not previously processed, sender identifier available.
Failure → do not start LangGraph, record the rejected event, return the
expected Meta response.

### Layer 2 — Interpretation
Intent known, requested operation registered, required arguments
identified, no invented/unsupported operation.

### Layer 3 — Plan
Every step uses an allowed operation, step order valid, write steps have
verification steps, schema/config changes include approval steps, max step
count respected.

### Layer 4 — Permission
User active, project access exists, required permission true, approver is
a *different, appropriately-roled* `agent_users` row where segregation is
required, approval not expired, approval payload matches the current
operation.

### Layer 5 — Tool result
Result is a dict, `success` is explicitly `true`, operation identifier
exists, reads return bounded rows, writes return exactly one affected row
with a record ID, no hidden error present.

### Layer 6 — Post-write
Read the written row back by ID; verify `project_id`, `record_type`,
canonical values, JSONB fields, creator, and row count.

### Layer 7 — Goal
Every planned operation completed, every write verified, all required
approvals recorded, no unresolved error, every final claim supported by
freshly-read verified data.

---

## 8. Preventing false success

HTTP 200 or "no exception raised" is never sufficient. Use a strict result
envelope:

```json
{
  "success": true,
  "operation": "add_project_row",
  "operation_id": "uuid",
  "record_id": "uuid",
  "affected_rows": 1,
  "data": {},
  "warnings": [],
  "error": null
}
```

```python
def validate_write_result(result: dict) -> dict:
    if not isinstance(result, dict):
        return failure("INVALID_RESULT_TYPE")
    if result.get("success") is not True:
        return failure("TOOL_REPORTED_FAILURE")
    if result.get("affected_rows") != 1:
        return failure("UNEXPECTED_AFFECTED_ROWS")
    if not result.get("record_id"):
        return failure("MISSING_RECORD_ID")
    return {"success": True, "code": "WRITE_RESULT_VALID"}


def verify_insert(project_id, expected, write_result):
    stored = get_record_by_id(write_result["record_id"])
    if stored is None:
        return failure("RECORD_NOT_FOUND_AFTER_WRITE")
    if stored["project_id"] != project_id:
        return failure("PROJECT_ID_MISMATCH")
    mismatches = compare_normalized_values(expected=expected, actual=stored)
    if mismatches:
        return failure("READ_BACK_MISMATCH", details=mismatches)
    return {"success": True, "code": "WRITE_VERIFIED", "verified_record": stored}
```

---

## 9. Retry and correction

```python
MAX_AGENT_STEPS = 10
MAX_TRANSIENT_RETRIES = 2
MAX_REPLANS = 2
MAX_TOOL_CALLS_PER_RUN = 8
```

Auto-retry: network timeout, model-provider temporary failure, Supabase
temporary connection failure, HTTP 429/502/503/504.

Never auto-retry: permission denied, invalid data, ambiguous project,
missing required field, approval rejected, approval expired, read-back
mismatch, DB constraint violation, duplicate project code, unknown field.

```
Verification Failed
        ├── Transient           → Retry same operation
        ├── Agent planning error→ Re-plan once
        ├── Missing user input  → Save checkpoint, ask user (over WhatsApp)
        ├── Authorization error → Stop
        └── Data mismatch       → Re-read, then stop safely
```

Never blindly repeat an insert after a verification mismatch.

---

## 10. Idempotency and duplicate webhook protection

Meta may redeliver a webhook. Dedupe every incoming message on `message_id`:

```
Webhook received
    ├── Exists and complete   → return previous result
    ├── Exists and processing → acknowledge, no duplicate execution
    └── Does not exist        → create processing record
```

For writes, compute:

```python
idempotency_key = sha256(
    (message_id + selected_tool + canonical_json(tool_arguments)).encode()
).hexdigest()
```

If a request repeats, return the existing result instead of inserting again.

---

## 11. Human approval — WhatsApp only

There is no separate approval UI. The entire approval loop is two WhatsApp
messages: the agent's request and the approver's reply.

```
Field creation request example
--------------------------------
Approval required

Operation: Create project field
Project: Pipeline Alpha
Record type: daily_log
Field: workers_present
Type: integer
Required: No
Default: 0
Reason: Track daily workforce availability

Approval ID: APR-4821
Reply APPROVE APR-4821, REJECT APR-4821 <reason>, or EDIT APR-4821 <changes>
```

Interrupt node:

```python
from langgraph.types import interrupt

def approval_node(state):
    decision = interrupt({
        "approval_id": state["approval_id"],
        "operation": state["selected_tool"],
        "project_id": state["project_id"],
        "payload": state["tool_arguments"],
        "required_role": "project_admin",
        "allowed_decisions": ["approve", "edit", "reject"],
    })
    return {"approval_status": decision["decision"]}
```

Outcomes:

- **APPROVE** → execute the original request
- **EDIT** → store the modified payload, re-validate it, execute only after
  it passes validation
- **REJECT** → do not execute, record decision and reason
- **EXPIRED** → do not execute, require a new request

### What replaces "user verification" here

Since there is no separate identity-verification step anywhere in this
system, the approval step is the one place where a forged message would be
most damaging — so it gets its own explicit, deterministic checklist
instead of a generic auth layer. Do not accept a plain "YES" from whoever
initiated the request, and do not accept an approval from a sender that
merely *claims* the right role. The approving WhatsApp message must satisfy
all of:

- Sender hash matches an `agent_users` row with `is_active = true`
- That user's role and `user_project_access` row grant the required
  `can_approve_*` permission for this project and operation
- The message contains a valid, unexpired `approval_id` referencing an
  existing `pending_approvals` row with `status = pending`
- `approval_token_hash` (generated server-side when the approval request
  was sent) matches what's expected for that `approval_id` — this is the
  single extra safeguard standing in for identity verification, since
  WhatsApp sender numbers alone are spoofable at the display layer in some
  clients
- The payload referenced by the approval hasn't changed since the request
  was sent (hash comparison against `proposed_payload`)

If any of these fail, treat it as `REJECT` with `decision_reason:
"invalid_approval_context"` and do not execute.

---

## 12. Persistence and memory

Three distinct stores, never conflated:

- **Checkpoint state** (LangGraph, Postgres checkpointer) — what operation
  is in progress: current plan, pending field creation, approval status,
  current node, retry count, tool result, verification result. Use a
  production Postgres checkpointer; `InMemorySaver` loses state on process
  restart and must not be used past local dev.
- **Conversation memory** (`chat_sessions`) — recent multi-turn context
  only. Load a bounded window (last 6–10 messages).
- **Business memory** (`projects`, `project_records`,
  `project_field_definitions`) — always a fresh DB read. Never answer a
  business question from checkpoint or conversation memory.

```
LangGraph checkpoint        → What operation is in progress?
chat_sessions                → What was recently discussed?
Supabase business tables     → What is currently true?
agent_events                 → What actually happened?
```

---

## 13. Supabase RLS and secrets

Enable RLS and configure grants on every exposed table. Grants determine
which operations a role may attempt; RLS policies determine which rows
those operations apply to. `service_role` bypasses RLS and stays strictly
server-side.

```
Browser/WhatsApp → never receives the Supabase service key
Vercel           → stores secrets only in server environment variables
LangGraph        → never receives the raw key in state or prompts
Database service → uses scoped authenticated identity where possible
Admin transaction→ uses service role only inside a restricted server function
```

Even when a service-role client is required, perform deterministic
authorization first:

```python
authorize(
    user_id=state["user_id"],
    project_id=state["project_id"],
    operation=state["selected_tool"],
)
```

Every business query must explicitly filter by `project_id`.

---

## 14. LangSmith tracing

Send traces for: webhook processing, context loading, LLM requests, intent
classification, plan generation, permission decisions, approval
interruption, tool execution, read-back verification, correction routing,
final response.

```
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=...
LANGSMITH_PROJECT=construction-agent-production
LANGSMITH_ENDPOINT=https://api.smith.langchain.com
```

Use a consistent sanitized thread identifier across both systems:

```python
langgraph_config = {
    "configurable": {"thread_id": state["thread_id"]},
    "metadata": {
        "run_id": state["run_id"],
        "user_hash": state["sender_hash"],
        "environment": "production",
    },
}
```

Never send to LangSmith: Supabase keys, Meta access tokens, raw phone
numbers, payment identifiers, private vendor data unless required, full
DB connection strings, unmasked personal information.

LangSmith is for operational observability, debugging, and evaluation.
Permanent approval and compliance audit stays in Supabase.

---

## 15. Durable audit events

Record every one of these into `agent_events`:

```
REQUEST_RECEIVED, MESSAGE_DEDUPLICATED, IDENTITY_RESOLVED, MEMORY_LOADED,
INTENT_CLASSIFIED, PLAN_CREATED, PLAN_VALIDATED, PROJECT_RESOLVED,
PERMISSION_CHECKED, APPROVAL_REQUESTED, APPROVAL_RECEIVED, TOOL_STARTED,
TOOL_SUCCEEDED, TOOL_FAILED, RESULT_VALIDATED, READ_BACK_STARTED,
READ_BACK_COMPLETED, VERIFICATION_PASSED, VERIFICATION_FAILED,
RETRY_STARTED, REPLAN_STARTED, GOAL_EVALUATED, RESPONSE_GENERATED,
RESPONSE_SENT, RUN_COMPLETED, RUN_FAILED
```

```json
{
  "run_id": "99a4...",
  "sequence_number": 8,
  "event_type": "VERIFICATION_PASSED",
  "status": "success",
  "node_name": "verify_write",
  "tool_name": "add_project_row",
  "input_json": {"record_id": "238f..."},
  "output_json": {"matched_fields": 8, "mismatches": []},
  "duration_ms": 31
}
```

Note: since there is no separate `IDENTITY_VERIFIED` event — identity
resolution is folded into `IDENTITY_RESOLVED` — that event's `output_json`
should record which `agent_users.id` was matched (or that no match was
found) so the audit trail still shows exactly who the system believed it
was talking to.

---

## 16. LangSmith evaluation plan

Deterministic evaluators to build: correct tool selected, project resolved
correctly, no unauthorized tool executed, approval obtained where required,
write read-back verification passed, final response contains no unverified
claims, max step count respected, no duplicate operation occurred.

Example dataset rows:

```json
{"input": "Show expenses for Pipeline Alpha", "expected": {"tool": "read_project_data", "record_type": "expense", "write_allowed": false}}
{"input": "Add workers_present to Pipeline Alpha", "expected": {"tool": "create_project_field", "approval_required": true, "direct_execution_allowed": false}}
{"input": "Create Mumbai Metro Phase 2", "expected": {"tool": "create_project", "approver_role": "system_admin", "approval_required": true}}
```

Run evaluations before deployment, and after any change to: prompts, this
instructions file, tool schemas, LangGraph routing, or permission policy.

---

## 17. Vercel request lifecycle

```
1. Meta calls Vercel webhook
2. Vercel acknowledges valid request
3. Application checks message idempotency
4. Application creates or resumes a LangGraph thread
5. Graph executes bounded nodes
6. If it reaches approval:
   - Save checkpoint
   - Save pending approval
   - Send approval message over WhatsApp
   - Function exits
7. Approver responds in a later webhook (also over WhatsApp)
8. Vercel loads saved thread ID
9. Graph resumes with Command(resume=...)
10. Tool executes
11. Read-back verification runs
12. Final reply is sent over WhatsApp
```

Human approval must never keep a Vercel function open — the graph pauses,
saves state, and exits; a future webhook resumes it.

```json
// vercel.json
{
  "$schema": "https://openapi.vercel.sh/vercel.json",
  "functions": {
    "api/index.py": { "maxDuration": 60 }
  }
}
```

The permitted maximum depends on the active Vercel plan. Every node, retry,
and model call needs its own timeout so the graph never relies on the
function itself for a long block.

---

## 18. Implementation sequence

> **Superseded for actual build order by `IMPLEMENTATION_STAGES.md`.**
> The phase breakdown below groups work by architectural layer (DB, then
> tools, then verification, then graph, then observability, then deploy)
> — useful for understanding dependencies between pieces, but it means
> nothing is end-to-end testable until Phase 4 is done. The staged
> version cuts across these phases so something real ships after every
> stage. Use this section as a checklist of pieces that must eventually
> all exist, not as the order to build them in.

**Phase 1 — Database foundation**
1. `projects` · 2. `project_records` · 3. `project_field_definitions` ·
4. `agent_users` · 5. `user_project_access` · 6. `agent_runs` +
`agent_events` · 7. `pending_approvals` · 8. `processed_messages` ·
9. Enable RLS and grants on all of the above.

**Phase 2 — Tool consolidation**
10. `read_project_data` · 11. `add_project_row` · 12. `create_project_field`
· 13. `create_project` · 14. Standardize result envelopes ·
15. Idempotency keys.

**Phase 3 — Verification**
16. Result validation · 17. Row read-back verification · 18. Project
creation verification · 19. Field-definition verification · 20.
Transactional rollback.

**Phase 4 — LangGraph**
21. `AgentState` · 22. Graph nodes · 23. Conditional routing · 24. Retry
and correction loops · 25. Postgres checkpointer · 26. Interrupts and
WhatsApp-driven resume flow.

**Phase 5 — Observability**
27. LangSmith tracing · 28. Agent event recording · 29. Trace metadata ·
30. Error classification · 31. Evaluation datasets.

**Phase 6 — Deployment**
32. Configure Vercel · 33. Environment variables · 34. Function duration ·
35. Deploy preview · 36. Run permission and failure tests (including
forged/invalid approval attempts, per §11) · 37. Deploy production.

---

## 19. Ownership principle (keep this true at every layer you build)

```
Supabase business tables      → What is true
LangGraph state + checkpoints → What is currently happening
Supabase agent audit tables   → What permanently happened
LangSmith                     → Why the agent behaved that way, and how well
Vercel                        → Where each HTTP execution runs
```
