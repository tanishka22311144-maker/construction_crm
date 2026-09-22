from typing import Any, Optional
from pydantic import BaseModel, Field


class ReadProjectDataInput(BaseModel):
    project_name: Optional[str] = Field(None, description="Name or code of the project to query")
    project_id: Optional[str] = Field(None, description="UUID of the project to query")
    record_type: Optional[str] = Field(
        None,
        description="Type of records to fetch: 'daily_log', 'expense', 'equipment_log', or None for all",
    )
    limit: int = Field(20, description="Max number of records to return (capped at 50 server-side)")
    filters: Optional[dict[str, Any]] = Field(default_factory=dict, description="Key-value filters on record fields")


class AddProjectRowInput(BaseModel):
    project_name: Optional[str] = Field(None, description="Name or code of the target project")
    project_id: Optional[str] = Field(None, description="UUID of the target project")
    record_type: str = Field(..., description="Record category: 'daily_log', 'expense', or 'equipment_log'")
    record_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD (defaults to today)")
    title: Optional[str] = Field(None, description="Brief title or subject")
    description: Optional[str] = Field(None, description="Additional context or notes")
    amount: Optional[float] = Field(None, description="Numeric cost or quantity")
    unit: Optional[str] = Field("INR", description="Unit of measurement or currency")
    data: dict[str, Any] = Field(default_factory=dict, description="Domain attributes (e.g. category, vendor)")


class CreateProjectFieldInput(BaseModel):
    project_name: Optional[str] = Field(None, description="Target project name")
    project_id: Optional[str] = Field(None, description="Target project UUID")
    record_type: str = Field(..., description="Target record type: 'daily_log', 'expense', 'equipment_log'")
    field_name: str = Field(..., description="Unique attribute identifier")
    field_type: str = Field(..., description="Type: 'text', 'integer', 'numeric', 'boolean', 'date', 'enum'")
    required: bool = Field(False, description="Whether this field must be present")
    default_value: Optional[Any] = Field(None, description="Optional default value")
    validation_rules: dict[str, Any] = Field(default_factory=dict, description="Validation constraints (min, max, etc.)")
    reason: Optional[str] = Field(None, description="Business justification for this field")


class CreateProjectInput(BaseModel):
    project_name: str = Field(..., description="Unique name of the construction project")
    project_code: str = Field(..., description="Unique alphanumeric code (e.g. MLE-01)")
    location: Optional[str] = Field(None, description="Geographic location or site address")
    status: str = Field("active", description="Project status: 'planned', 'active', 'completed', 'on_hold'")
    default_record_types: list[str] = Field(
        default_factory=lambda: ["daily_log", "expense", "equipment_log"],
        description="Record types to enable for this project",
    )
