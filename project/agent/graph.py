from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes import (
    check_permission,
    execute_tool,
    generate_grounded_response,
    load_identity_and_memory,
    load_instructions,
    receive_request,
    resolve_project,
    safe_failure,
    send_whatsapp_response,
    understand_request,
)
from agent.state import AgentState


def route_permission(state: AgentState) -> str:
    """Conditional routing function after permission check."""
    perm = state.get("permission_result") or {}
    if perm.get("allowed"):
        return "allowed"
    return "denied"


def build_graph():
    builder = StateGraph(AgentState)

    # Register nodes
    builder.add_node("receive_request", receive_request)
    builder.add_node("load_instructions", load_instructions)
    builder.add_node("load_identity_and_memory", load_identity_and_memory)
    builder.add_node("understand_request", understand_request)
    builder.add_node("resolve_project", resolve_project)
    builder.add_node("check_permission", check_permission)
    builder.add_node("execute_tool", execute_tool)
    builder.add_node("generate_grounded_response", generate_grounded_response)
    builder.add_node("safe_failure", safe_failure)
    builder.add_node("send_whatsapp_response", send_whatsapp_response)

    # Set entry point
    builder.set_entry_point("receive_request")

    # Linear edges
    builder.add_edge("receive_request", "load_instructions")
    builder.add_edge("load_instructions", "load_identity_and_memory")
    builder.add_edge("load_identity_and_memory", "understand_request")
    builder.add_edge("understand_request", "resolve_project")
    builder.add_edge("resolve_project", "check_permission")

    # Conditional edge on check_permission
    builder.add_conditional_edges(
        "check_permission",
        route_permission,
        {
            "allowed": "execute_tool",
            "denied": "safe_failure",
        },
    )

    # Execution success branch
    builder.add_edge("execute_tool", "generate_grounded_response")
    builder.add_edge("generate_grounded_response", "send_whatsapp_response")

    # Safe failure branch
    builder.add_edge("safe_failure", "send_whatsapp_response")

    # Completion
    builder.add_edge("send_whatsapp_response", END)

    # TODO(stage-4): MemorySaver is temporary for Stage 2 & 3.
    # Stage 4 replaces this with PostgresSaver (langgraph-checkpoint-postgres).
    checkpointer = MemorySaver()

    return builder.compile(checkpointer=checkpointer)


# Compiled LangGraph instance exported for runtime invocation
graph = build_graph()
