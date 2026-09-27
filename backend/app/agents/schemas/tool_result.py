"""Standardized typed ToolResult schema for the Maya v2 dumb tool layer."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar
from pydantic import BaseModel, Field


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ToolStatus = Literal[
    "success",
    "error",
    "blocked",
    "timeout",
    "not_configured",
]


class SearchHit(BaseModel):
    """Typed single web search result item returned by SearchService."""
    title: str = ""
    url: str
    content: str = ""


class WebSearchPayload(BaseModel):
    """Typed payload for web_search tool execution."""
    query: str
    source: str = "tavily_live_search"
    results: List[SearchHit] = Field(default_factory=list)


PayloadT = TypeVar("PayloadT")


class ToolResult(BaseModel, Generic[PayloadT]):
    """Uniform typed return contract for all tool executions in Maya v2.

    Separates operational states per Rev 3 frozen contract:
    `success`, `error`, `blocked`, `timeout`, and `not_configured`.
    """
    tool_id: str = Field(..., description="Canonical tool identifier, e.g., 'web_search'")
    status: ToolStatus = Field(
        ...,
        description="Operational status: 'success', 'error', 'blocked', 'timeout', or 'not_configured'",
    )
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured tool output payload")
    error_code: Optional[str] = Field(default=None, description="Machine-readable error code when status != 'success'")
    error_message: Optional[str] = Field(default=None, description="Human-readable error diagnostic")
    started_at: str = Field(default_factory=_utc_now)
    completed_at: str = Field(default_factory=_utc_now)

    @classmethod
    def ok(
        cls,
        tool_id: str,
        data: Dict[str, Any],
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> "ToolResult":
        now = _utc_now()
        return cls(
            tool_id=tool_id,
            status="success",
            data=data,
            error_code=None,
            error_message=None,
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

    @classmethod
    def fail(
        cls,
        tool_id: str,
        error_code: str,
        error_message: str,
        data: Optional[Dict[str, Any]] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> "ToolResult":
        now = _utc_now()
        return cls(
            tool_id=tool_id,
            status="error",
            data=data or {},
            error_code=error_code,
            error_message=error_message,
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

    @classmethod
    def blocked(
        cls,
        tool_id: str,
        error_message: str,
        error_code: str = "POLICY_BLOCKED",
        data: Optional[Dict[str, Any]] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> "ToolResult":
        now = _utc_now()
        return cls(
            tool_id=tool_id,
            status="blocked",
            data=data or {},
            error_code=error_code,
            error_message=error_message,
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

    @classmethod
    def timeout(
        cls,
        tool_id: str,
        error_message: str,
        error_code: str = "TOOL_TIMEOUT",
        data: Optional[Dict[str, Any]] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> "ToolResult":
        now = _utc_now()
        return cls(
            tool_id=tool_id,
            status="timeout",
            data=data or {},
            error_code=error_code,
            error_message=error_message,
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

    @classmethod
    def not_configured(
        cls,
        tool_id: str,
        error_message: str,
        error_code: str = "NOT_CONFIGURED",
        data: Optional[Dict[str, Any]] = None,
        started_at: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> "ToolResult":
        now = _utc_now()
        return cls(
            tool_id=tool_id,
            status="not_configured",
            data=data or {},
            error_code=error_code,
            error_message=error_message,
            started_at=started_at or now,
            completed_at=completed_at or now,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Compatibility helper for legacy callers reading dict-style keys."""
        if key in ("tool_id", "status", "data", "error_code", "error_message", "started_at", "completed_at"):
            return getattr(self, key)
        return self.data.get(key, default)

    def __getitem__(self, key: str) -> Any:
        if key in ("tool_id", "status", "data", "error_code", "error_message", "started_at", "completed_at"):
            return getattr(self, key)
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in ("tool_id", "status", "data", "error_code", "error_message", "started_at", "completed_at") or key in self.data
