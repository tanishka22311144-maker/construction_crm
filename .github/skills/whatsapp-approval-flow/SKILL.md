---
name: whatsapp-approval-flow
description: How to send, validate, and resume approval requests when WhatsApp is the only approval UI
---

# WhatsApp-only approval flow

There is no dashboard. The full loop is two WhatsApp messages.

Outbound message shape:

```
Approval required

Operation: <human-readable operation>
Project: <project_name>
<key fields...>

Approval ID: APR-XXXX
Reply APPROVE APR-XXXX, REJECT APR-XXXX <reason>, or EDIT APR-XXXX <changes>
```

Inbound validation — ALL of these must pass, or treat as REJECT with
`decision_reason: "invalid_approval_context"`:

1. Sender hash → active `agent_users` row
2. That user's role + `user_project_access` grants the specific
   `can_approve_*` permission for this operation/project
3. Message references a valid, unexpired `approval_id` with
   `pending_approvals.status = pending`
4. `approval_token_hash` (generated server-side at request time) matches
5. Hash of the referenced `proposed_payload` still matches what's stored
   (guards against approving a payload that changed after the request
   went out)

Interrupt node pattern:

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

The node must save checkpoint state and let the Vercel function exit —
never block waiting inside the invocation. A later webhook (the
approver's reply) resumes the same `thread_id` with `Command(resume=...)`.

EDIT decisions must be re-validated through the same schema checks as a
fresh tool call before execution — never execute an edited payload
straight from the approval message.
