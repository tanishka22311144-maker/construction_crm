from .nodes import generate_response, receive_request, send_whatsapp_response


def run_agent(state: dict) -> dict:
    state.setdefault("debug_trace", [])
    steps = [
        ("receive_request", receive_request),
        ("generate_response", generate_response),
        ("send_whatsapp_response", send_whatsapp_response),
    ]

    for step_name, step_func in steps:
        state["debug_trace"].append({"step": step_name, "status": "started"})
        try:
            state = step_func(state)
            state["debug_trace"].append({"step": step_name, "status": "ok"})
        except Exception as exc:  # pragma: no cover - runtime safeguard
            state["debug_trace"].append({
                "step": step_name,
                "status": "error",
                "error": str(exc),
                "type": type(exc).__name__,
            })
            raise

    return state
