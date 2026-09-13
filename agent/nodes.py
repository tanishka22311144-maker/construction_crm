import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib import error, request

from services.authorization import authorize
from services.database import execute_query
from tools.read_project_data import read_project_data


def _debug_log(step: str, **details):
    if os.getenv("DEBUG_LOGS", "1").lower() in {"0", "false", "no", "off"}:
        return
    payload = {"event": "agent_trace", "step": step}
    for key, value in details.items():
        if isinstance(value, str) and ("token" in key.lower() or "key" in key.lower()):
            payload[key] = "***redacted***"
        elif isinstance(value, str) and len(value) > 200:
            payload[key] = value[:200] + "..."
        else:
            payload[key] = value
    print(json.dumps(payload, default=str), flush=True)


def load_local_env():
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = [part.strip() for part in line.split("=", 1)]
        os.environ.setdefault(key, value)


load_local_env()


def _instructions_text() -> str:
    instruction_path = Path(__file__).resolve().parent / "instructions.md"
    if instruction_path.exists():
        return instruction_path.read_text(encoding="utf-8")
    return "You are a helpful construction CRM assistant."


def _get_llm_reply(user_message: str, system_prompt: Optional[str] = None) -> str:
    api_key = (os.getenv("GROQ_API_KEY") or "").strip().strip('"').strip("'")
    configured_model = (os.getenv("GROQ_MODEL") or "").strip().strip('"').strip("'")
    candidate_models = []
    if configured_model:
        candidate_models.append(configured_model)
    candidate_models.extend([
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "qwen/qwen3.8-27b",
        "groq/compound-mini",
    ])

    _debug_log(
        "llm_start",
        configured_model=configured_model,
        candidate_models=candidate_models,
        api_key_present=bool(api_key),
        message_preview=(user_message[:160] if user_message else ""),
    )

    if not api_key:
        _debug_log("llm_missing_api_key")
        return (
            "I’m ready to help, but GROQ_API_KEY is not configured yet. "
            "Set it in your environment to enable live LLM replies."
        )

    seen = set()
    for model in candidate_models:
        if model and model not in seen:
            seen.add(model)
            try:
                _debug_log("llm_attempt", model=model)
                response = _call_groq(api_key, model, user_message, system_prompt)
                if response:
                    _debug_log("llm_success", model=model, response_preview=response[:180])
                    return response
            except Exception as exc:
                _debug_log("llm_attempt_failed", model=model, error=str(exc)[:200])
                continue

    _debug_log("llm_failure", configured_model=configured_model, candidate_count=len(candidate_models))
    return (
        "The Groq model request is failing for all configured candidates. "
        "Please verify GROQ_MODEL and GROQ_API_KEY in the environment."
    )


def _call_groq(api_key: str, model: str, user_message: str, system_prompt: Optional[str]) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": (system_prompt or _instructions_text())},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": 512,
    }

    req = request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "ConstructionCRM/1.0",
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        _debug_log("groq_http_error", model=model, status=exc.code, detail=str(exc)[:200])
        if exc.code in (401, 403):
            raise RuntimeError("groq_auth_error") from exc
        if exc.code in (404, 400):
            raise RuntimeError("groq_model_unavailable") from exc
        raise RuntimeError(f"groq_http_error:{exc.code}") from exc
    except (error.URLError, TimeoutError, ValueError) as exc:
        _debug_log("groq_network_error", model=model, error=str(exc)[:200])
        raise RuntimeError("groq_network_error") from exc

    try:
        choice = payload_json["choices"][0]
        message = choice.get("message", {})
        content = message.get("content")
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        if isinstance(content, str) and content.strip():
            return content.strip()
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            return reasoning.strip()
        return "I’m ready to help with your construction project question."
    except (KeyError, IndexError, TypeError):
        return "I couldn’t parse a valid response from the model."


# --- Graph Nodes for Stage 2 ---

def receive_request(state: dict) -> dict:
    state.setdefault("thread_id", state.get("thread_id") or f"thread-{uuid.uuid4().hex[:12]}")
    state.setdefault("run_id", f"run-{uuid.uuid4().hex[:12]}")
    state.setdefault("message_id", state.get("message_id") or f"msg-{uuid.uuid4().hex[:12]}")
    state.setdefault("debug_trace", [])

    incoming_message = state.get("incoming_message") or ""
    state["incoming_message"] = incoming_message
    state["messages"] = [{"role": "user", "content": incoming_message}]

    # Derive sender_hash if sender_wa_id is present and sender_hash not already set
    sender_wa_id = state.get("sender_wa_id")
    if sender_wa_id and not state.get("sender_hash"):
        sender_hash = hashlib.sha256(str(sender_wa_id).strip().encode("utf-8")).hexdigest()
        state["sender_hash"] = sender_hash

    _debug_log(
        "receive_request",
        thread_id=state["thread_id"],
        run_id=state["run_id"],
        sender_hash=state.get("sender_hash"),
        incoming_message_preview=incoming_message[:160],
    )
    return state


def load_instructions(state: dict) -> dict:
    """Load instructions fresh from instructions.md per PROJECT_SPEC.md §3."""
    instructions = _instructions_text()
    state["instructions"] = instructions
    _debug_log("load_instructions", length=len(instructions))
    return state


def load_identity_and_memory(state: dict) -> dict:
    """Look up active user in agent_users matching sender_hash."""
    sender_hash = state.get("sender_hash")
    if not sender_hash:
        _debug_log("load_identity_no_sender_hash")
        state["user_id"] = None
        return state

    query = """
        SELECT id, display_name, role, is_active
        FROM public.agent_users
        WHERE whatsapp_sender_hash = %s AND is_active = true
        LIMIT 1
    """
    try:
        rows = execute_query(query, (sender_hash,), sender_hash=sender_hash)
        if rows:
            user_row = rows[0]
            state["user_id"] = str(user_row["id"])
            state["user_role"] = user_row.get("role")
            state["user_name"] = user_row.get("display_name")
            _debug_log("load_identity_found", user_id=state["user_id"], role=state.get("user_role"))
        else:
            state["user_id"] = None
            _debug_log("load_identity_not_found", sender_hash=sender_hash)
    except Exception as exc:
        _debug_log("load_identity_error", error=str(exc))
        state["user_id"] = None

    return state


def understand_request(state: dict) -> dict:
    """Stage 2 simplified request understanding: determine if read request and extract project reference."""
    incoming = (state.get("incoming_message") or "").strip()
    lower = incoming.lower()

    # Determine record type if specified
    record_type = None
    if "expense" in lower or "cost" in lower or "spent" in lower:
        record_type = "expense"
    elif "daily log" in lower or "site log" in lower or "log" in lower:
        record_type = "daily_log"
    elif "equipment" in lower or "machinery" in lower:
        record_type = "equipment_log"

    state["intent"] = "read"
    state["selected_tool"] = "read_project_data"

    # Attempt to extract project name hint from message (e.g., "for Project Alpha" or "in Metro Line")
    project_name_match = re.search(r'(?:for|in|project)\s+([A-Za-z0-9_\-\s]+)', incoming, re.IGNORECASE)
    extracted_name = None
    if project_name_match:
        extracted_name = project_name_match.group(1).strip()
        # Clean trailing punctuation or keywords
        extracted_name = re.sub(r'[\?\.\!].*$', '', extracted_name).strip()

    state["project_name"] = extracted_name
    state["tool_arguments"] = {
        "record_type": record_type,
        "limit": 20,
    }
    _debug_log("understand_request", intent=state["intent"], project_name=state["project_name"], record_type=record_type)
    return state


def resolve_project(state: dict) -> dict:
    """Resolve project_name to a verified project_id from public.projects."""
    project_name = state.get("project_name")
    user_id = state.get("user_id")

    query = "SELECT id, project_name, project_code FROM public.projects"
    params: list[Any] = []

    if project_name:
        query += " WHERE project_name ILIKE %s OR project_code ILIKE %s"
        params.extend([f"%{project_name}%", f"%{project_name}%"])

    query += " LIMIT 5"

    try:
        rows = execute_query(query, tuple(params) if params else None, user_id=user_id)
        if len(rows) == 1:
            state["project_id"] = str(rows[0]["id"])
            state["project_name"] = rows[0]["project_name"]
            _debug_log("resolve_project_exact", project_id=state["project_id"], project_name=state["project_name"])
        elif len(rows) > 1 and project_name:
            # Pick first match if exact match on code/name
            exact = [r for r in rows if r["project_name"].lower() == project_name.lower() or r["project_code"].lower() == project_name.lower()]
            if exact:
                state["project_id"] = str(exact[0]["id"])
                state["project_name"] = exact[0]["project_name"]
            else:
                state["project_id"] = str(rows[0]["id"])
                state["project_name"] = rows[0]["project_name"]
            _debug_log("resolve_project_multiple", project_id=state["project_id"])
        elif len(rows) == 0 and not project_name:
            # Fallback if no project name given and query without filter returned none
            state["project_id"] = None
        else:
            state["project_id"] = None
            _debug_log("resolve_project_none", search_term=project_name)
    except Exception as exc:
        _debug_log("resolve_project_error", error=str(exc))
        state["project_id"] = None

    return state


def check_permission(state: dict) -> dict:
    """Verify authorization before executing any tool."""
    user_id = state.get("user_id")
    project_id = state.get("project_id")
    operation = state.get("selected_tool") or "read_project_data"

    auth_result = authorize(user_id=user_id, project_id=project_id, operation=operation)
    state["permission_result"] = auth_result
    _debug_log("check_permission", allowed=auth_result.get("allowed"), reason=auth_result.get("reason"))
    return state


def execute_tool(state: dict) -> dict:
    """Execute read_project_data tool inside bound session context."""
    project_id = state.get("project_id")
    user_id = state.get("user_id")
    tool_args = state.get("tool_arguments", {})
    record_type = tool_args.get("record_type")
    limit = tool_args.get("limit", 20)

    result = read_project_data(
        project_id=project_id,
        record_type=record_type,
        limit=limit,
        user_id=user_id,
    )
    state["tool_result"] = result
    _debug_log("execute_tool", status=result.get("status"), count=result.get("count"))
    return state


def generate_grounded_response(state: dict) -> dict:
    """Synthesize final user response grounded strictly in tool data."""
    tool_result = state.get("tool_result", {})
    records = tool_result.get("records", [])
    project_name = state.get("project_name") or "the project"
    record_type = state.get("tool_arguments", {}).get("record_type") or "records"

    if not records:
        state["final_response"] = f"No {record_type} found for {project_name}."
        state["goal_complete"] = True
        return state

    # Format record summary
    summary_lines = [f"Found {len(records)} {record_type} for {project_name}:"]
    for idx, r in enumerate(records[:10], 1):
        date_str = str(r.get("record_date") or "")
        title = r.get("title") or r.get("description") or "Entry"
        amount_part = f" - ${r['amount']}" if r.get("amount") is not None else ""
        unit_part = f" ({r['unit']})" if r.get("unit") else ""
        summary_lines.append(f"{idx}. {date_str}: {title}{amount_part}{unit_part}")

    state["final_response"] = "\n".join(summary_lines)
    state["goal_complete"] = True
    _debug_log("generate_grounded_response_done", response_preview=state["final_response"][:160])
    return state


def safe_failure(state: dict) -> dict:
    """Safe exit path when validation, identity, or permissions fail."""
    perm = state.get("permission_result", {})
    user_id = state.get("user_id")
    project_id = state.get("project_id")

    if not user_id:
        msg = "Your WhatsApp number is not registered or active in the construction CRM."
    elif not project_id:
        msg = f"Could not find or resolve project '{state.get('project_name') or ''}'. Please specify a valid project name."
    elif not perm.get("allowed"):
        msg = f"Access denied: {perm.get('reason', 'You do not have permission to access this project.')}"
    else:
        msg = "An error occurred while processing your request. Please try again or contact your admin."

    state["final_response"] = msg
    state["goal_complete"] = False
    _debug_log("safe_failure", message=msg)
    return state


def send_whatsapp_response(state: dict) -> dict:
    state.setdefault("final_response", "Hello from the construction CRM bot.")
    _debug_log("send_whatsapp_response", final_response_preview=state.get("final_response", "")[:180])
    return state
