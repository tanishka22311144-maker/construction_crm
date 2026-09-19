import json
import os
import re
import uuid
from pathlib import Path
from typing import Any, Optional
from urllib import error, request

from services.audit import load_recent_chat_history, record_chat_session
from services.authorization import authorize
from services.database import execute_query
from services.identity import hash_whatsapp_number
from services.verification import validate_read_result, classify_error
from tools.read_project_data import read_project_data

# Bounded execution limits per PROJECT_SPEC.md §9
MAX_AGENT_STEPS = 10
MAX_TRANSIENT_RETRIES = 2
MAX_REPLANS = 2
MAX_TOOL_CALLS_PER_RUN = 8


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
    state.setdefault("step_count", 0)
    state.setdefault("retry_count", 0)
    state.setdefault("replan_count", 0)

    incoming_message = state.get("incoming_message") or ""
    state["incoming_message"] = incoming_message
    state["messages"] = [{"role": "user", "content": incoming_message}]

    # Derive sender_hash if sender_wa_id is present and sender_hash not already set
    sender_wa_id = state.get("sender_wa_id")
    if sender_wa_id and not state.get("sender_hash"):
        state["sender_hash"] = hash_whatsapp_number(sender_wa_id)

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
    if not sender_hash and state.get("sender_wa_id"):
        sender_hash = hash_whatsapp_number(state.get("sender_wa_id"))
        state["sender_hash"] = sender_hash

    if not sender_hash:
        _debug_log("load_identity_result", sender_hash=None, result="not_matched", reason="missing_sender_hash")
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
            _debug_log("load_identity_result", sender_hash=sender_hash, result="matched", role=state.get("user_role"))

            # Stage 4: Load multi-turn conversation history from chat_sessions
            history = load_recent_chat_history(state["user_id"], sender_hash=sender_hash, limit=6)
            if history:
                messages = []
                for turn in history:
                    messages.append({"role": "user", "content": turn["user_message"]})
                    messages.append({"role": "assistant", "content": turn["assistant_reply"]})
                incoming = state.get("incoming_message") or ""
                messages.append({"role": "user", "content": incoming})
                state["messages"] = messages
                _debug_log("load_memory_history_loaded", turns=len(history))
        else:
            state["user_id"] = None
            _debug_log("load_identity_result", sender_hash=sender_hash, result="not_matched")
    except Exception as exc:
        _debug_log("load_identity_error", error=str(exc))
        state["user_id"] = None

    return state


def understand_request(state: dict) -> dict:
    """Use LLM to classify intent and extract project reference from the user message."""
    incoming = (state.get("incoming_message") or "").strip()
    instructions = state.get("instructions") or _instructions_text()

    classification_prompt = f"""You are classifying a WhatsApp message sent to a construction CRM assistant.

Message: "{incoming}"

Respond with ONLY a JSON object (no markdown, no explanation) with these fields:
- "intent": one of "read", "write", "unsupported"
- "record_type": one of "expense", "daily_log", "equipment_log", or null if not specified
- "project_name": the project name or code mentioned, or null if not mentioned

Example: {{"intent": "read", "record_type": "expense", "project_name": "Metro Line Extension"}}"""

    llm_response = _get_llm_reply(classification_prompt, system_prompt=instructions)

    # Try to parse LLM output as JSON
    intent = "read"
    record_type = None
    extracted_name = None

    try:
        # Strip markdown fences if present
        cleaned = llm_response.strip().strip("```json").strip("```").strip()
        parsed = json.loads(cleaned)
        intent = parsed.get("intent", "read")
        record_type = parsed.get("record_type")
        extracted_name = parsed.get("project_name")
        _debug_log("understand_request_llm", intent=intent, record_type=record_type, project_name=extracted_name)
    except (json.JSONDecodeError, AttributeError):
        # Fallback: basic keyword regex
        lower = incoming.lower()
        if "expense" in lower or "cost" in lower or "spent" in lower:
            record_type = "expense"
        elif "daily log" in lower or "site log" in lower:
            record_type = "daily_log"
        elif "equipment" in lower or "machinery" in lower:
            record_type = "equipment_log"
        m = re.search(r'(?:for|in|project)\s+([A-Za-z0-9_\-\s]+)', incoming, re.IGNORECASE)
        if m:
            extracted_name = re.sub(r'[\?\.\!].*$', '', m.group(1)).strip()
        _debug_log("understand_request_fallback", intent=intent, record_type=record_type, project_name=extracted_name)

    state["intent"] = intent
    state["selected_tool"] = "read_project_data" if intent == "read" else None
    state["project_name"] = extracted_name
    state["tool_arguments"] = {"record_type": record_type, "limit": 20}
    return state


def create_plan(state: dict) -> dict:
    """Stage 3: Break request into explicit operational steps."""
    intent = state.get("intent", "read")
    selected_tool = state.get("selected_tool")

    if intent == "read" and selected_tool == "read_project_data":
        plan = [
            {"step": 1, "action": "resolve_project"},
            {"step": 2, "action": "check_permission"},
            {"step": 3, "action": "read_project_data"},
            {"step": 4, "action": "evaluate_goal"},
        ]
    else:
        plan = [
            {"step": 1, "action": "unsupported"},
        ]

    state["plan"] = plan
    state["current_step"] = 1
    state["requested_outcome"] = f"Query {state.get('tool_arguments', {}).get('record_type') or 'records'} for {state.get('project_name') or 'project'}"
    _debug_log("create_plan", plan=plan, replan_count=state.get("replan_count", 0))
    return state


def validate_plan(state: dict) -> dict:
    """Stage 3: Validate plan actions against allowed operations and bounded limits."""
    plan = state.get("plan") or []
    allowed_actions = {"resolve_project", "check_permission", "read_project_data", "evaluate_goal"}

    if not plan:
        state["plan_valid"] = False
        state["error_reason"] = "Plan is empty."
        _debug_log("validate_plan_empty")
        return state

    for step in plan:
        action = step.get("action")
        if action not in allowed_actions:
            state["plan_valid"] = False
            state["error_reason"] = f"Operation '{action}' is unsupported. In Stage 3, only reading project records is supported."
            state["final_response"] = "I can only help query project records (expenses, daily logs, equipment logs) at this time. Other operations are not supported yet."
            _debug_log("validate_plan_unsupported_action", action=action)
            return state

    state["plan_valid"] = True
    _debug_log("validate_plan_success", steps=len(plan))
    return state


def resolve_project(state: dict) -> dict:
    """Resolve project_name to a verified project_id from public.projects.

    Per PROJECT_SPEC.md §5 & §9:
    - Exact match -> proceed to permission check
    - Ambiguous / multiple matches -> ask_user (do not guess)
    - No match -> ask_user (do not guess)
    """
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
            state["resolution_status"] = "exact"
            _debug_log("resolve_project_exact", project_id=state["project_id"], project_name=state["project_name"])
        elif len(rows) > 1 and project_name:
            # Check for exact case-insensitive match on name or code
            exact = [
                r for r in rows
                if r["project_name"].lower() == project_name.lower() or r["project_code"].lower() == project_name.lower()
            ]
            if len(exact) == 1:
                state["project_id"] = str(exact[0]["id"])
                state["project_name"] = exact[0]["project_name"]
                state["resolution_status"] = "exact"
                _debug_log("resolve_project_exact_case_insensitive", project_id=state["project_id"])
            else:
                state["project_id"] = None
                state["resolution_status"] = "ambiguous"
                match_names = ", ".join([f"'{r['project_name']}'" for r in rows[:3]])
                state["final_response"] = f"Which project did you mean? Found multiple possibilities: {match_names}."
                _debug_log("resolve_project_ambiguous", search_term=project_name, count=len(rows))
        elif len(rows) > 1 and not project_name:
            # User didn't specify any project and there are multiple projects
            state["project_id"] = None
            state["resolution_status"] = "ambiguous"
            match_names = ", ".join([f"'{r['project_name']}'" for r in rows[:3]])
            state["final_response"] = f"Please specify a project. Available projects: {match_names}."
            _debug_log("resolve_project_no_name_multiple")
        else:
            state["project_id"] = None
            state["resolution_status"] = "not_found"
            state["final_response"] = f"Could not find any project matching '{project_name or ''}'. Please specify a valid project name."
            _debug_log("resolve_project_not_found", search_term=project_name)
    except Exception as exc:
        _debug_log("resolve_project_error", error=str(exc))
        state["project_id"] = None
        state["resolution_status"] = "error"
        state["final_response"] = "An error occurred while looking up the project."

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


def validate_tool_result(state: dict) -> dict:
    """Stage 3: Structural verification of tool result and transient retry classification."""
    tool_result = state.get("tool_result") or {}
    verification = validate_read_result(tool_result)
    state["verification_result"] = verification

    if verification["valid"]:
        state["validation_status"] = "valid"
        _debug_log("validate_tool_result_passed", row_count=verification.get("row_count"))
        return state

    # Failure handling
    state["last_error"] = {
        "code": verification.get("code"),
        "error": verification.get("error"),
        "category": verification.get("category"),
    }

    if verification.get("is_transient"):
        retry_count = state.get("retry_count", 0) + 1
        state["retry_count"] = retry_count
        if retry_count <= MAX_TRANSIENT_RETRIES:
            state["validation_status"] = "retry"
            _debug_log("validate_tool_result_retry", attempt=retry_count, max_retries=MAX_TRANSIENT_RETRIES)
            return state
        else:
            state["validation_status"] = "failed"
            state["final_response"] = f"The database query timed out after {MAX_TRANSIENT_RETRIES} attempts. Please try again in a few moments."
            _debug_log("validate_tool_result_max_retries_exceeded")
            return state

    # Fatal / non-retryable error
    state["validation_status"] = "failed"
    state["final_response"] = f"Query failed: {verification.get('error')}"
    _debug_log("validate_tool_result_fatal", code=verification.get("code"))
    return state


def evaluate_goal(state: dict) -> dict:
    """Stage 3: Verify if the requested goal is fulfilled, or if replanning is needed."""
    # Increment execution step count
    step_count = state.get("step_count", 0) + 1
    state["step_count"] = step_count

    if step_count > MAX_AGENT_STEPS:
        state["evaluation_status"] = "exceeded"
        state["goal_complete"] = False
        state["final_response"] = "The request exceeded the maximum allowed execution steps."
        _debug_log("evaluate_goal_exceeded_steps", step_count=step_count)
        return state

    verification = state.get("verification_result") or {}
    if verification.get("valid"):
        state["goal_complete"] = True
        state["evaluation_status"] = "complete"
        _debug_log("evaluate_goal_complete")
        return state

    # Check replan count
    replan_count = state.get("replan_count", 0)
    if replan_count < MAX_REPLANS:
        state["replan_count"] = replan_count + 1
        state["evaluation_status"] = "replan"
        _debug_log("evaluate_goal_replan", replan_count=state["replan_count"])
        return state

    state["goal_complete"] = False
    state["evaluation_status"] = "failed"
    _debug_log("evaluate_goal_failed")
    return state


def generate_grounded_response(state: dict) -> dict:
    """Pass real DB records to the LLM and produce a grounded natural-language reply."""
    tool_result = state.get("tool_result", {})
    records = tool_result.get("records", [])
    project_name = state.get("project_name") or "the project"
    record_type = state.get("tool_arguments", {}).get("record_type") or "records"
    incoming = state.get("incoming_message", "")
    instructions = state.get("instructions") or _instructions_text()

    if not records:
        # No data — still ask the LLM to phrase this naturally
        grounding = f"No {record_type} records were found for project '{project_name}'."
    else:
        # Serialize records as compact plain-text context (no SQL, no internal IDs)
        lines = [f"Data retrieved — {len(records)} {record_type} record(s) for project '{project_name}':"]
        for i, r in enumerate(records[:20], 1):
            date_str = str(r.get("record_date") or "")
            title = r.get("title") or r.get("description") or "Entry"
            unit = r.get("unit", "")
            unit_prefix = "$" if unit == "USD" else ""
            amount = f", amount: {unit_prefix}{r['amount']} {unit}".strip() if r.get("amount") is not None else ""
            lines.append(f"  {i}. {date_str} — {title}{amount}")
        grounding = "\n".join(lines)

    # Stage 4: Add recent conversation history if present
    conversation_context = ""
    history_messages = state.get("messages") or []
    if len(history_messages) > 1:
        prior_turns = []
        for msg in history_messages[:-1]:
            role = "User" if msg.get("role") == "user" else "Assistant"
            prior_turns.append(f"{role}: {msg.get('content')}")
        if prior_turns:
            conversation_context = "Recent conversation context:\n" + "\n".join(prior_turns[-4:]) + "\n\n"

    synthesis_prompt = (
        f"{conversation_context}"
        f"Current question from user (via WhatsApp): \"{incoming}\"\n\n"
        f"{grounding}\n\n"
        "Write a brief, friendly WhatsApp reply that answers the user based strictly on the data above and previous conversation. "
        "Do not invent any information not present in the data. Keep it under 5 lines."
    )

    llm_reply = _get_llm_reply(synthesis_prompt, system_prompt=instructions)

    # If LLM is unconfigured (e.g. unit tests / offline dev), fall back to structured grounding text
    if "GROQ_API_KEY is not configured" in llm_reply or "failing for all configured" in llm_reply:
        state["final_response"] = f"Here is the retrieved data:\n{grounding}"
    else:
        state["final_response"] = llm_reply

    state["goal_complete"] = True
    _debug_log("generate_grounded_response_done", response_preview=state["final_response"][:160])
    return state


def safe_failure(state: dict) -> dict:
    """Safe exit path when validation, identity, or permissions fail."""
    # If a specific final_response was already prepared, preserve it
    if state.get("final_response"):
        state["goal_complete"] = False
        _debug_log("safe_failure_preserved", message=state["final_response"])
        return state

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
        msg = state.get("error_reason") or "An error occurred while processing your request. Please try again or contact your admin."

    state["final_response"] = msg
    state["goal_complete"] = False
    _debug_log("safe_failure", message=msg)
    return state


def send_whatsapp_response(state: dict) -> dict:
    state.setdefault("final_response", "Hello from the construction CRM bot.")
    final_response = state.get("final_response", "")

    # Stage 4: Persist conversation turn to chat_sessions for durable memory
    user_id = state.get("user_id")
    incoming = state.get("incoming_message", "")
    if user_id and incoming and final_response:
        record_chat_session(
            user_id=user_id,
            user_message=incoming,
            assistant_reply=final_response,
            run_id=state.get("run_id"),
            sender_hash=state.get("sender_hash"),
        )

    _debug_log("send_whatsapp_response", final_response_preview=final_response[:180])
    return state
