"""Dumb, single-query Tavily web search service for Maya v2 (Phase 2).

Invariants enforced:
- 1 call = 1 query (zero hidden query expansion or keyword heuristics)
- `include_answer=False` (no LLM-synthesized Tavily answers masquerading as primary evidence)
- No fabricated offline fallback result
- Every failure is returned as a typed `ToolResult` with `status="error"`
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from typing import Any, Callable, Dict, List, Optional
import requests

from app.agents.schemas.tool_result import SearchHit, ToolResult, WebSearchPayload

TAVILY_SEARCH_URL = "https://api.tavily.com/search"
MAX_QUERY_CHARS = 380
MAX_EXCERPT_CHARS = 900


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SearchService:
    """Stateless, single-query Tavily search wrapper."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        http_post: Optional[Callable[..., Any]] = None,
        timeout_seconds: float = 20.0,
    ) -> None:
        self._api_key = api_key
        self._http_post = http_post
        self.timeout_seconds = timeout_seconds

    def _resolve_api_key(self) -> str:
        if self._api_key is not None:
            return self._api_key.strip()
        return (os.getenv("TAVILY_API_KEY") or "").strip()

    def search(self, query: str, max_results: int = 8) -> ToolResult:
        """Execute exactly one Tavily search query and return a typed ToolResult."""
        started_at = _utc_now()
        clean_query = (query or "").strip()
        if not clean_query:
            return ToolResult.fail(
                tool_id="web_search",
                error_code="EMPTY_QUERY",
                error_message="Search query cannot be empty.",
                data={"query": "", "results": []},
                started_at=started_at,
                completed_at=_utc_now(),
            )

        api_key = self._resolve_api_key()
        if not api_key:
            return ToolResult.not_configured(
                tool_id="web_search",
                error_code="MISSING_API_KEY",
                error_message="TAVILY_API_KEY is missing or empty.",
                data={"query": clean_query, "results": []},
                started_at=started_at,
                completed_at=_utc_now(),
            )

        post_fn = self._http_post or requests.post
        request_body: Dict[str, Any] = {
            "api_key": api_key,
            "query": clean_query[:MAX_QUERY_CHARS],
            "search_depth": "advanced",
            "include_answer": False,
            "max_results": max(1, min(int(max_results), 20)),
        }

        try:
            resp = post_fn(
                TAVILY_SEARCH_URL,
                json=request_body,
                timeout=self.timeout_seconds,
            )
            resp.raise_for_status()
            raw_json = resp.json()
        except requests.Timeout as exc:
            return ToolResult.timeout(
                tool_id="web_search",
                error_code="TAVILY_TIMEOUT",
                error_message=f"Tavily search timed out after {self.timeout_seconds}s: {exc}",
                data={"query": clean_query, "results": []},
                started_at=started_at,
                completed_at=_utc_now(),
            )
        except requests.HTTPError as exc:
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            code_str = f"TAVILY_HTTP_{status_code}" if status_code else "TAVILY_HTTP_ERROR"
            return ToolResult.fail(
                tool_id="web_search",
                error_code=code_str,
                error_message=f"Tavily HTTP error: {exc}",
                data={"query": clean_query, "results": []},
                started_at=started_at,
                completed_at=_utc_now(),
            )
        except Exception as exc:
            return ToolResult.fail(
                tool_id="web_search",
                error_code="TAVILY_REQUEST_ERROR",
                error_message=f"Tavily search failed: {exc}",
                data={"query": clean_query, "results": []},
                started_at=started_at,
                completed_at=_utc_now(),
            )

        seen_urls: set[str] = set()
        hits: List[SearchHit] = []
        raw_results = raw_json.get("results", []) if isinstance(raw_json, dict) else []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            hits.append(
                SearchHit(
                    title=str(item.get("title") or "").strip(),
                    url=url,
                    content=str(item.get("content") or "")[:MAX_EXCERPT_CHARS],
                )
            )

        payload = WebSearchPayload(
            query=clean_query,
            source="tavily_live_search",
            results=hits,
        )
        return ToolResult.ok(
            tool_id="web_search",
            data=payload.model_dump(),
            started_at=started_at,
            completed_at=_utc_now(),
        )


def search_web(
    query: str,
    *,
    max_results: int = 8,
    api_key: Optional[str] = None,
    http_post: Optional[Callable[..., Any]] = None,
) -> ToolResult:
    """Module-level convenience function for single-query Tavily web search."""
    service = SearchService(api_key=api_key, http_post=http_post)
    return service.search(query=query, max_results=max_results)
