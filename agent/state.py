from typing import TypedDict, Optional

try:
    from typing_extensions import Annotated
    from langgraph.graph.message import add_messages
except Exception:  # pragma: no cover - local fallback for minimal runtime environments
    Annotated = list  # type: ignore[misc]

    def add_messages(messages):
        return messages


class AgentState(TypedDict, total=False):
    # Identity
    run_id: str
    thread_id: str
    user_id: str
    sender_hash: str
    message_id: str

    # Conversation
    messages: Annotated[list, add_messages]
    incoming_message: str

    # Request interpretation
    intent: Optional[str]
    requested_outcome: Optional[str]
    missing_fields: list[str]

    # Project context
    project_id: Optional[str]
    project_name: Optional[str]

    # Plan
    plan: list[dict]
    plan_valid: bool
    current_step: int
    selected_tool: Optional[str]
    tool_arguments: dict

    # Security
    risk_level: Optional[str]
    permission_result: dict
    human_approval_required: bool
    approval_id: Optional[str]
    approval_status: Optional[str]

    # Execution
    tool_result: dict
    verification_result: dict
    validation_status: Optional[str]
    evaluation_status: Optional[str]

    # Correction control
    retry_count: int
    replan_count: int
    step_count: int
    last_error: Optional[dict]
    resolution_status: Optional[str]
    error_reason: Optional[str]

    # Completion
    goal_complete: bool
    final_response: Optional[str]
    debug_trace: list[dict]
