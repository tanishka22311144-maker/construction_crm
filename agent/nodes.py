import json
import os
import uuid
from pathlib import Path
from urllib import error, request


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


def _get_llm_reply(user_message: str, system_prompt: str | None = None) -> str:
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


def _call_groq(api_key: str, model: str, user_message: str, system_prompt: str | None) -> str:
    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": (system_prompt or _instructions_text())[:200]},
            {"role": "user", "content": user_message[:200]},
        ],
        "temperature": 0.1,
        "max_tokens": 64,
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
    _debug_log("groq_request", model=model, message_preview=user_message[:160], payload_model=model)

    try:
        with request.urlopen(req, timeout=30) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
            _debug_log(
                "groq_response",
                model=model,
                status=getattr(response, "status", None),
                usage=payload_json.get("usage", {}),
            )
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
            result = content.strip()
            _debug_log("groq_content_ready", model=model, response_preview=result[:180])
            return result
        reasoning = message.get("reasoning")
        if isinstance(reasoning, str) and reasoning.strip():
            result = reasoning.strip()
            _debug_log("groq_reasoning_ready", model=model, response_preview=result[:180])
            return result
        return "I’m ready to help with your construction project question."
    except (KeyError, IndexError, TypeError):
        _debug_log("groq_parse_failure", model=model, payload_preview=json.dumps(payload_json)[:200])
        return "I couldn’t parse a valid response from the model."


def receive_request(state: dict) -> dict:
    state.setdefault("thread_id", f"stage1-{uuid.uuid4().hex[:12]}")
    state.setdefault("run_id", f"run-{uuid.uuid4().hex[:12]}")
    state.setdefault("message_id", state.get("message_id") or f"msg-{uuid.uuid4().hex[:12]}")
    state.setdefault("debug_trace", [])

    incoming_message = state.get("incoming_message") or ""
    state["incoming_message"] = incoming_message
    state["messages"] = [{"role": "user", "content": incoming_message}]
    _debug_log(
        "receive_request",
        thread_id=state["thread_id"],
        run_id=state["run_id"],
        message_id=state["message_id"],
        incoming_message_preview=incoming_message[:160],
    )
    return state


def generate_response(state: dict) -> dict:
    incoming_message = state.get("incoming_message") or ""
    _debug_log("generate_response_start", thread_id=state.get("thread_id"), incoming_message_preview=incoming_message[:160])
    response_text = _get_llm_reply(incoming_message, system_prompt=_instructions_text())
    state["final_response"] = response_text
    state["goal_complete"] = True
    _debug_log("generate_response_done", thread_id=state.get("thread_id"), final_response_preview=response_text[:180])
    return state


def send_whatsapp_response(state: dict) -> dict:
    state.setdefault("final_response", "Hello from the construction CRM bot.")
    _debug_log("send_whatsapp_response", thread_id=state.get("thread_id"), final_response_preview=state["final_response"][:180])
    return state

