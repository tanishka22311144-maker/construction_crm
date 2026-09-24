import os
import sys
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from agent.nodes import (
    check_permission,
    classify_risk_node as classify_risk,
    create_plan,
    evaluate_goal,
    execute_tool,
    generate_grounded_response,
    load_identity_and_memory,
    load_instructions,
    receive_request,
    request_approval,
    resolve_project,
    resume_after_approval,
    safe_failure,
    send_whatsapp_response,
    understand_request,
    validate_plan,
    validate_tool_result,
    verify_operation,
)
from agent.state import AgentState


def route_identity(state: AgentState) -> str:
    """Route based on user identity resolution."""
    if state.get("user_id"):
        return "authenticated"
    return "unauthenticated"


def route_plan(state: AgentState) -> str:
    """Route based on plan validation."""
    if state.get("plan_valid"):
        return "valid"
    return "invalid"


def route_project(state: AgentState) -> str:
    """Route based on project name resolution (Layer 3/5)."""
    status = state.get("resolution_status")
    if status == "exact":
        return "exact"
    return "ask_user"


def route_permission(state: AgentState) -> str:
    """Conditional routing function after permission check."""
    perm = state.get("permission_result") or {}
    if perm.get("allowed"):
        return "allowed"
    return "denied"


def route_risk(state: AgentState) -> str:
    """Route based on risk classification and approval requirement."""
    if state.get("human_approval_required"):
        return "approval_required"
    return "execute"


def route_approval_resume(state: AgentState) -> str:
    """Route after resuming from approval."""
    status = (state.get("approval_status") or "").strip().lower()
    if status in ("approved", "approve"):
        return "approved"
    if status in ("edited", "edit"):
        return "edited"
    if status == "pending":
        return "pending"
    return "failed"


def route_tool_result(state: AgentState) -> str:
    """Route based on tool result verification (transient retry vs fatal)."""
    status = state.get("validation_status")
    if status == "valid":
        return "valid"
    if status == "retry":
        return "retry"
    return "failed"


def route_goal(state: AgentState) -> str:
    """Route after goal evaluation (complete vs replan vs exceeded)."""
    status = state.get("evaluation_status")
    if status == "complete":
        return "complete"
    if status == "replan":
        return "replan"
    return "failed"


def build_graph():
    builder = StateGraph(AgentState)

    # Register nodes per PROJECT_SPEC.md §5
    builder.add_node("receive_request", receive_request)
    builder.add_node("load_instructions", load_instructions)
    builder.add_node("load_identity_and_memory", load_identity_and_memory)
    builder.add_node("understand_request", understand_request)
    builder.add_node("create_plan", create_plan)
    builder.add_node("validate_plan", validate_plan)
    builder.add_node("resolve_project", resolve_project)
    builder.add_node("check_permission", check_permission)
    builder.add_node("classify_risk", classify_risk)
    builder.add_node("request_approval", request_approval)
    builder.add_node("resume_after_approval", resume_after_approval)
    builder.add_node("execute_tool", execute_tool)
    builder.add_node("validate_tool_result", validate_tool_result)
    builder.add_node("verify_operation", verify_operation)
    builder.add_node("evaluate_goal", evaluate_goal)
    builder.add_node("generate_grounded_response", generate_grounded_response)
    builder.add_node("safe_failure", safe_failure)
    builder.add_node("send_whatsapp_response", send_whatsapp_response)

    # Entry point
    builder.set_entry_point("receive_request")

    # Flow sequence
    builder.add_edge("receive_request", "load_instructions")
    builder.add_edge("load_instructions", "load_identity_and_memory")

    # Identity check edge
    builder.add_conditional_edges(
        "load_identity_and_memory",
        route_identity,
        {
            "authenticated": "understand_request",
            "unauthenticated": "safe_failure",
        },
    )

    # Planning edges
    builder.add_edge("understand_request", "create_plan")
    builder.add_edge("create_plan", "validate_plan")

    # Plan validation edge
    builder.add_conditional_edges(
        "validate_plan",
        route_plan,
        {
            "valid": "resolve_project",
            "invalid": "safe_failure",
        },
    )

    # Project resolution edge (exact match -> permission, ambiguous/none -> ask_user)
    builder.add_conditional_edges(
        "resolve_project",
        route_project,
        {
            "exact": "check_permission",
            "ask_user": "send_whatsapp_response",
        },
    )

    # Permission check edge -> routes to classify_risk if allowed
    builder.add_conditional_edges(
        "check_permission",
        route_permission,
        {
            "allowed": "classify_risk",
            "denied": "safe_failure",
        },
    )

    # Risk classification edge
    builder.add_conditional_edges(
        "classify_risk",
        route_risk,
        {
            "approval_required": "request_approval",
            "execute": "execute_tool",
        },
    )

    # Approval request -> on resume proceeds to resume_after_approval
    builder.add_edge("request_approval", "resume_after_approval")

    # Approval resume edge
    builder.add_conditional_edges(
        "resume_after_approval",
        route_approval_resume,
        {
            "approved": "execute_tool",
            "edited": "validate_plan",
            "pending": "send_whatsapp_response",
            "failed": "safe_failure",
        },
    )

    # Tool execution -> tool result verification (Layer 5)
    builder.add_edge("execute_tool", "validate_tool_result")

    # Tool result validation edge (valid -> verify_operation, retry -> execute_tool, failed -> safe_failure)
    builder.add_conditional_edges(
        "validate_tool_result",
        route_tool_result,
        {
            "valid": "verify_operation",
            "retry": "execute_tool",
            "failed": "safe_failure",
        },
    )

    # Layer 6 post-write verification edge (valid -> evaluate_goal, failed -> safe_failure)
    builder.add_conditional_edges(
        "verify_operation",
        route_tool_result,
        {
            "valid": "evaluate_goal",
            "retry": "execute_tool",
            "failed": "safe_failure",
        },
    )

    # Goal evaluation edge (complete -> generate_grounded_response, replan -> create_plan, failed -> safe_failure)
    builder.add_conditional_edges(
        "evaluate_goal",
        route_goal,
        {
            "complete": "generate_grounded_response",
            "replan": "create_plan",
            "failed": "safe_failure",
        },
    )

    # Grounded response and failure termination
    builder.add_edge("generate_grounded_response", "send_whatsapp_response")
    builder.add_edge("safe_failure", "send_whatsapp_response")
    builder.add_edge("send_whatsapp_response", END)

    # LangGraph API / Studio manages its own persistence and forbids custom checkpointers.
    if "langgraph_api" in sys.modules or os.getenv("LANGGRAPH_API") or any("langgraph" in arg for arg in sys.argv):
        return builder.compile()

    # Stage 4: Postgres checkpointer when available and configured
    checkpointer = None
    db_url = os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL")
    if db_url:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            # Use connection string if PostgresSaver available
            # checkpointer = PostgresSaver.from_conn_string(db_url)
            # checkpointer.setup()
            checkpointer = MemorySaver()
        except Exception:
            checkpointer = MemorySaver()
    else:
        checkpointer = MemorySaver()

    return builder.compile(checkpointer=checkpointer)


# Compiled LangGraph instance exported for runtime invocation
graph = build_graph()
