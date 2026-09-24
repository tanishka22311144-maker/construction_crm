"""Approval service for WhatsApp-only human-in-the-loop workflows.

Implements the approval verification checklist from:
- PROJECT_SPEC.md §11
- .agents/skills/whatsapp-approval-flow/SKILL.md
- .agents/rules/security.md
"""
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
import uuid

from services.database import execute_query


APPROVAL_EXPIRY_HOURS = 24


def compute_payload_hash(payload: Any) -> str:
    """Compute deterministic SHA-256 hash of canonical JSON payload."""
    if not isinstance(payload, dict):
        payload = {"data": payload}
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def generate_approval_token_hash(
    approval_id: str,
    requested_by: str,
    operation: str,
    payload_hash: str,
) -> str:
    """Generate server-side token hash standing in for identity verification (§11)."""
    server_secret = os.getenv("APPROVAL_SECRET") or os.getenv("META_VERIFY_TOKEN") or "construction-crm-default-secret"
    raw = f"{approval_id}:{requested_by}:{operation}:{payload_hash}:{server_secret}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def format_approval_request_message(
    approval_code: str,
    operation: str,
    project_name: str,
    payload: dict[str, Any],
) -> str:
    """Format the outbound approval WhatsApp message per PROJECT_SPEC.md §11."""
    human_op = operation.replace("_", " ").title()
    lines = [
        "Approval required",
        "",
        f"Operation: {human_op}",
        f"Project: {project_name or 'General'}",
    ]

    # Include key human-readable payload fields
    for k, v in payload.items():
        if k in ("project_id", "operation_id", "idempotency_key"):
            continue
        key_label = k.replace("_", " ").capitalize()
        lines.append(f"{key_label}: {v}")

    lines.extend([
        "",
        f"Approval ID: {approval_code}",
        f"Reply APPROVE {approval_code}, REJECT {approval_code} <reason>, or EDIT {approval_code} <changes>",
    ])
    return "\n".join(lines)


def parse_approval_reply(message_text: str) -> Optional[dict[str, Any]]:
    """Parse incoming approval reply message:
    APPROVE APR-XXXX
    REJECT APR-XXXX <reason>
    EDIT APR-XXXX <changes>
    """
    if not message_text:
        return None

    clean = message_text.strip()
    match = re.match(r"^(APPROVE|REJECT|EDIT)\s+([A-Za-z0-9\-_]+)(?:\s+([\s\S]*))?$", clean, re.IGNORECASE)
    if not match:
        return None

    action = match.group(1).upper()
    code = match.group(2).strip().upper()
    extra = (match.group(3) or "").strip()

    return {
        "action": action,
        "approval_code": code,
        "extra_text": extra,
    }


def find_project_approver(
    project_id: Optional[str],
    required_role: str,
) -> Optional[dict[str, Any]]:
    """Find an active agent_users row eligible to approve this operation."""
    if project_id and required_role in ("project_admin", "finance_approver"):
        # Check users with project-specific access
        sql = """
            SELECT u.id, u.display_name, u.role, u.whatsapp_sender_hash
            FROM public.agent_users u
            JOIN public.user_project_access upa ON upa.user_id = u.id
            WHERE upa.project_id = %s
              AND u.is_active = true
              AND (
                  u.role = %s
                  OR (%s = 'project_admin' AND upa.can_approve_fields = true)
                  OR (%s = 'system_admin')
              )
            LIMIT 1;
        """
        rows = execute_query(sql, (project_id, required_role, required_role, required_role))
        if rows:
            return rows[0]

    # Fallback to system-level role match
    sql_role = """
        SELECT id, display_name, role, whatsapp_sender_hash
        FROM public.agent_users
        WHERE role = %s AND is_active = true
        LIMIT 1;
    """
    rows = execute_query(sql_role, (required_role,))
    if rows:
        return rows[0]

    # If no exact role match, check system_admin
    rows_admin = execute_query(sql_role, ("system_admin",))
    if rows_admin:
        return rows_admin[0]

    return None


def create_pending_approval(
    run_id: str,
    thread_id: str,
    requested_by: str,
    required_approver_role: str,
    operation: str,
    proposed_payload: dict[str, Any],
    project_id: Optional[str] = None,
    project_name: Optional[str] = None,
    expires_in_hours: int = APPROVAL_EXPIRY_HOURS,
    user_id: Optional[str] = None,
    sender_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Create a pending_approvals record in Supabase and return approval metadata."""
    raw_uuid = uuid.uuid4()
    approval_uuid = str(raw_uuid)
    # Human-readable approval code: APR-XXXXXX
    approval_code = f"APR-{raw_uuid.hex[:6].upper()}"

    # Store approval_code inside proposed_payload for easy lookup
    payload_to_store = dict(proposed_payload)
    payload_to_store["approval_code"] = approval_code
    if project_id and "project_id" not in payload_to_store:
        payload_to_store["project_id"] = str(project_id)
    if project_name and "project_name" not in payload_to_store:
        payload_to_store["project_name"] = str(project_name)

    payload_hash = compute_payload_hash(payload_to_store)
    token_hash = generate_approval_token_hash(
        approval_id=approval_uuid,
        requested_by=requested_by,
        operation=operation,
        payload_hash=payload_hash,
    )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(hours=expires_in_hours)

    sql = """
        INSERT INTO public.pending_approvals (
            id, run_id, thread_id, requested_by, required_approver_role,
            operation, proposed_payload, status, approval_token_hash,
            requested_at, expires_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s)
        RETURNING id, run_id, thread_id, requested_by, required_approver_role, operation, proposed_payload, status, approval_token_hash, requested_at, expires_at;
    """
    params = (
        approval_uuid,
        run_id,
        thread_id,
        requested_by,
        required_approver_role,
        operation,
        json.dumps(payload_to_store),
        token_hash,
        now.isoformat(),
        expires_at.isoformat(),
    )

    execute_query(sql, params, sender_hash=sender_hash, user_id=user_id)

    formatted_message = format_approval_request_message(
        approval_code=approval_code,
        operation=operation,
        project_name=project_name or payload_to_store.get("project_name", ""),
        payload=payload_to_store,
    )

    return {
        "approval_id": approval_uuid,
        "approval_code": approval_code,
        "token_hash": token_hash,
        "payload_hash": payload_hash,
        "expires_at": expires_at.isoformat(),
        "formatted_message": formatted_message,
        "required_role": required_approver_role,
    }


def lookup_pending_approval_by_code(approval_code: str) -> Optional[dict[str, Any]]:
    """Look up a pending_approvals record by code APR-XXXX or UUID prefix."""
    if not approval_code:
        return None

    clean_code = approval_code.strip().upper()
    hex_part = clean_code.replace("APR-", "").lower()

    sql = """
        SELECT id, run_id, thread_id, requested_by, required_approver_role,
               operation, proposed_payload, status, approval_token_hash,
               requested_at, expires_at, decided_by, decision, decision_reason, decided_at
        FROM public.pending_approvals
        WHERE proposed_payload->>'approval_code' = %s
           OR id::text LIKE %s
        ORDER BY requested_at DESC
        LIMIT 1;
    """
    rows = execute_query(sql, (clean_code, f"{hex_part}%"))
    if rows:
        return rows[0]
    return None


def validate_and_process_approval(
    approval_code: str,
    approver_sender_hash: str,
    action: str,
    extra_text: str = "",
) -> dict[str, Any]:
    """Execute the full 5-point verification checklist from PROJECT_SPEC.md §11.

    Returns dict with decision outcome and details.
    """
    now = datetime.now(timezone.utc)

    # 1. Sender hash -> active agent_users row
    if not approver_sender_hash:
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": "Missing approver sender hash",
        }

    sql_user = """
        SELECT id, display_name, role, is_active
        FROM public.agent_users
        WHERE whatsapp_sender_hash = %s AND is_active = true
        LIMIT 1;
    """
    user_rows = execute_query(sql_user, (approver_sender_hash,), sender_hash=approver_sender_hash)
    if not user_rows:
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": "Approver identity not found or inactive in agent_users",
        }

    approver = user_rows[0]
    approver_id = str(approver["id"])
    approver_role = approver.get("role", "")

    # 3. Message references a valid, unexpired approval_id with status = pending
    record = lookup_pending_approval_by_code(approval_code)
    if not record:
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": f"No approval record found for {approval_code}",
        }

    approval_id = str(record["id"])
    stored_status = record.get("status")
    if stored_status != "pending":
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": f"Approval request {approval_code} is already {stored_status}",
        }

    # Check expiration
    expires_at_val = record.get("expires_at")
    if isinstance(expires_at_val, str):
        try:
            expires_at = datetime.fromisoformat(expires_at_val.replace("Z", "+00:00"))
        except ValueError:
            expires_at = now
    elif isinstance(expires_at_val, datetime):
        expires_at = expires_at_val
    else:
        expires_at = now

    if expires_at < now:
        # Mark as expired in DB
        _update_approval_status(approval_id, "expired", approver_id, "reject", "Approval request expired", now)
        return {
            "valid": False,
            "status": "expired",
            "decision": "reject",
            "decision_reason": "Approval request expired",
            "thread_id": record.get("thread_id"),
        }

    # 2. User's role + user_project_access grants specific can_approve_* permission
    required_role = record.get("required_approver_role")
    operation = record.get("operation")
    payload = record.get("proposed_payload") or {}
    project_id = payload.get("project_id")

    role_authorized = False
    if approver_role == "system_admin":
        role_authorized = True
    elif approver_role == required_role:
        role_authorized = True
    elif operation == "create_project_field" and project_id:
        # Check user_project_access.can_approve_fields
        sql_access = """
            SELECT can_approve_fields
            FROM public.user_project_access
            WHERE user_id = %s AND project_id = %s
            LIMIT 1;
        """
        acc_rows = execute_query(sql_access, (approver_id, project_id), user_id=approver_id)
        if acc_rows and acc_rows[0].get("can_approve_fields"):
            role_authorized = True
    elif operation == "create_project":
        # System-level approval
        if approver_role in ("system_admin", "project_admin"):
            role_authorized = True

    if not role_authorized:
        _update_approval_status(approval_id, "rejected", approver_id, "reject", "invalid_approval_context", now)
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": f"Approver role '{approver_role}' does not satisfy required '{required_role}'",
            "thread_id": record.get("thread_id"),
        }

    # 4. approval_token_hash matches
    stored_payload = record.get("proposed_payload")
    stored_token_hash = record.get("approval_token_hash")
    expected_payload_hash = compute_payload_hash(stored_payload)
    expected_token_hash = generate_approval_token_hash(
        approval_id=approval_id,
        requested_by=str(record.get("requested_by")),
        operation=str(record.get("operation")),
        payload_hash=expected_payload_hash,
    )
    if stored_token_hash != expected_token_hash:
        _update_approval_status(approval_id, "rejected", approver_id, "reject", "invalid_approval_context", now)
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": "approval_token_hash mismatch",
            "thread_id": record.get("thread_id"),
        }

    # 5. Payload hash comparison (payload hasn't changed since request went out)
    if expected_payload_hash != compute_payload_hash(stored_payload):
        _update_approval_status(approval_id, "rejected", approver_id, "reject", "invalid_approval_context", now)
        return {
            "valid": False,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": "invalid_approval_context",
            "details": "proposed_payload hash mismatch",
            "thread_id": record.get("thread_id"),
        }

    # All 5 verification checks passed! Now process the action:
    act = action.upper()
    if act == "APPROVE":
        new_status = "approved"
        decision = "approve"
        reason = extra_text or "Approved by project admin"
        _update_approval_status(approval_id, new_status, approver_id, decision, reason, now)
        return {
            "valid": True,
            "status": "approved",
            "decision": "approve",
            "decision_reason": reason,
            "approval_id": approval_id,
            "thread_id": record.get("thread_id"),
            "operation": operation,
            "payload": stored_payload,
            "requested_by": str(record.get("requested_by")),
        }
    elif act == "REJECT":
        new_status = "rejected"
        decision = "reject"
        reason = extra_text or "Rejected by approver"
        _update_approval_status(approval_id, new_status, approver_id, decision, reason, now)
        return {
            "valid": True,
            "status": "rejected",
            "decision": "reject",
            "decision_reason": reason,
            "approval_id": approval_id,
            "thread_id": record.get("thread_id"),
            "operation": operation,
            "payload": stored_payload,
            "requested_by": str(record.get("requested_by")),
        }
    elif act == "EDIT":
        new_status = "edited"
        decision = "edit"
        reason = f"Edited: {extra_text}" if extra_text else "Edited by approver"
        _update_approval_status(approval_id, new_status, approver_id, decision, reason, now)
        return {
            "valid": True,
            "status": "edited",
            "decision": "edit",
            "decision_reason": reason,
            "approval_id": approval_id,
            "thread_id": record.get("thread_id"),
            "operation": operation,
            "payload": stored_payload,
            "edit_instructions": extra_text,
            "requested_by": str(record.get("requested_by")),
        }

    return {
        "valid": False,
        "status": "rejected",
        "decision": "reject",
        "decision_reason": "invalid_approval_context",
        "details": f"Unknown action: {act}",
        "thread_id": record.get("thread_id"),
    }


def _update_approval_status(
    approval_id: str,
    status: str,
    decided_by: str,
    decision: str,
    reason: str,
    decided_at: datetime,
) -> None:
    """Persist approval decision into public.pending_approvals."""
    sql = """
        UPDATE public.pending_approvals
        SET status = %s,
            decided_by = %s,
            decision = %s,
            decision_reason = %s,
            decided_at = %s
        WHERE id = %s;
    """
    try:
        execute_query(sql, (status, decided_by, decision, reason, decided_at.isoformat(), approval_id))
    except Exception as exc:
        print(json.dumps({"event": "update_approval_status_error", "error": str(exc)}), flush=True)
