---
name: idempotency-key
description: Dedup pattern for WhatsApp webhook redelivery and repeated writes
---

# Idempotency

Meta may redeliver the same webhook. Dedup on `message_id` before doing
anything else:

```
Webhook received
    ├── Exists in processed_messages and complete    → return previous result
    ├── Exists in processed_messages and processing   → acknowledge, no duplicate execution
    └── Does not exist                                 → create processing record
```

For any write tool call, compute a key and check it before inserting:

```python
idempotency_key = sha256(
    (message_id + selected_tool + canonical_json(tool_arguments)).encode()
).hexdigest()
```

If a request repeats (same key), return the previously stored result
instead of inserting a second row. Never rely on the WhatsApp client
side to avoid double-sends — assume redelivery will happen.
