from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

class ToolDefinition(BaseModel):
    id: str
    name: str
    description: str
    requires_approval: bool = False

class AIEmployeeSpec(BaseModel):
    id: str
    name: str
    role: str
    department: str = Field(description='Marketing, HRM, CRM, or Operations')
    avatar_emoji: str = '🤖'
    theme_color: str = 'blue'
    objective: str
    persona: str
    sops: List[str] = Field(default_factory=list, description='Standard Operating Procedures')
    tools: List[str] = Field(default_factory=list, description='List of tool IDs enabled')
    schedule_type: str = 'on_demand'  # on_demand, interval, daily
    schedule_interval_mins: Optional[int] = None
    requires_approval_for: List[str] = Field(default_factory=list)
    status: str = 'active'
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class CompilePromptRequest(BaseModel):
    prompt: str

class DispatchTaskRequest(BaseModel):
    task_prompt: Optional[str] = None

class ApprovalActionRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None

class TaskStep(BaseModel):
    step_number: int
    thought: str
    tool_called: Optional[str] = None
    tool_input: Optional[Dict[str, Any]] = None
    tool_output: Optional[Any] = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())

class TaskRecord(BaseModel):
    id: str
    employee_id: str
    employee_name: str
    task_prompt: str
    status: str = 'pending'  # pending, running, waiting_approval, completed, failed
    steps: List[Dict[str, Any]] = Field(default_factory=list)
    pending_action: Optional[Dict[str, Any]] = None
    final_output: Optional[str] = None
    tokens_used: int = 0
    cost_usd: float = 0.0004
    time_saved_mins: int = 20
    created_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    completed_at: Optional[str] = None
