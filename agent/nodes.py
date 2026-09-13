import json
import os
import uuid
from pathlib import Path
from urllib import request, error


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
    api_key = os.getenv("GROQ_API_KEY")
    configured_model = os.getenv("GROQ_MODEL")
    candidate_models = []
    if configured_model:
        candidate_models.append(configured_model)
    candidate_models.extend([
        "openai/gpt-oss-20b",
        "llama-3.1-8b-instant",
        "llama-3.3-70b-versatile",
    ])

    if not api_key:
        return (
            "I’m ready to help, but GROQ_API_KEY is not configured yet. "
            "Set it in your environment to enable live LLM replies."
        )

    seen = set()
    for model in candidate_models:
        if model and model not in seen:
            seen.add(model)
            try:
                response = _call_groq(api_key, model, user_message, system_prompt)
                if response:
                    return response
            except Exception:
                continue

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
        },
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=30) as response:
            payload_json = json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        if exc.code in (401, 403):
            raise RuntimeError("groq_auth_error") from exc
        if exc.code in (404, 400):
            raise RuntimeError("groq_model_unavailable") from exc
        raise RuntimeError(f"groq_http_error:{exc.code}") from exc
    except (error.URLError, TimeoutError, ValueError) as exc:
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


def receive_request(state: dict) -> dict:
    state.setdefault("thread_id", f"stage1-{uuid.uuid4().hex[:12]}")
    state.setdefault("run_id", f"run-{uuid.uuid4().hex[:12]}")
    state.setdefault("message_id", state.get("message_id") or f"msg-{uuid.uuid4().hex[:12]}")

    incoming_message = state.get("incoming_message") or ""
    state["incoming_message"] = incoming_message
    state["messages"] = [{"role": "user", "content": incoming_message}]
    return state


def generate_response(state: dict) -> dict:
    incoming_message = state.get("incoming_message") or ""
    response_text = _get_llm_reply(incoming_message, system_prompt=_instructions_text())
    state["final_response"] = response_text
    state["goal_complete"] = True
    return state


def send_whatsapp_response(state: dict) -> dict:
    state.setdefault("final_response", "Hello from the construction CRM bot.")
    return state

