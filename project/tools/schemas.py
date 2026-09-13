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
