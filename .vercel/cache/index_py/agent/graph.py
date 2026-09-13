from .nodes import generate_response, receive_request, send_whatsapp_response


def run_agent(state: dict) -> dict:
    state = receive_request(state)
    state = generate_response(state)
    state = send_whatsapp_response(state)
    return state
