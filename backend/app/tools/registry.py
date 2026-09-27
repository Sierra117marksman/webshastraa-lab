"""Dumb Tool Registry for Maya v2 (Phase 2).

Invariants enforced:
- The registry describes tools ONLY (`id`, `name`, `description`, `parameters`).
- Permission and approval authority lives exclusively in `PolicyEngine` + SQLite `permissions`.
- All tool executions return typed `ToolResult` objects.
- `execute_web_search` delegates to `SearchService` (1 call = 1 query, `include_answer=False`, no fake fallback).
- `execute_email_sender` HTML-escapes body content and has no hardcoded backup SMTP fallback.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import os
import re
import smtplib
from typing import Any, Callable, Dict, List, Optional
import requests

from app.agents.schemas.tool_result import ToolResult
from app.models.employee import ToolDefinition
from app.services.search_service import search_web


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


TOOLS_METADATA: List[Dict[str, Any]] = [
    {
        "id": "web_search",
        "name": "Live Web Search",
        "description": "Searches the live web for market trends, competitor updates, and prospect information.",
        "parameters": {"query": "string"},
    },
    {
        "id": "email_sender",
        "name": "Gmail SMTP Dispatcher",
        "description": "Drafts and dispatches real emails to prospects, candidates, or clients via Gmail SMTP.",
        "parameters": {"to": "string", "subject": "string", "body": "string"},
    },
    {
        "id": "sheet_logger",
        "name": "Spreadsheet / CRM Logger",
        "description": "Records structured data, candidate evaluations, or lead records into sheets.",
        "parameters": {"table": "string", "record": "dict"},
    },
    {
        "id": "slack_notifier",
        "name": "Team Channel Notifier",
        "description": "Posts alerts, daily briefings, or task summaries into Slack or Discord.",
        "parameters": {"channel": "string", "message": "string"},
    },
    {
        "id": "domain_verifier",
        "name": "SSRF-Safe Domain Footprint Verifier",
        "description": "Safely audits candidate websites for reachability, redirect chains, and platform/app signatures without SSRF risk.",
        "parameters": {"url": "string"},
    },
]

TOOL_DEFINITIONS: Dict[str, ToolDefinition] = {
    item["id"]: ToolDefinition(**item) for item in TOOLS_METADATA
}


def get_tool_definition(tool_id: str) -> Optional[ToolDefinition]:
    normalized = (tool_id or "").strip().lower()
    return TOOL_DEFINITIONS.get(normalized)


def execute_web_search(
    query: str,
    single_query: bool = True,
    *,
    max_results: int = 8,
    api_key: Optional[str] = None,
    http_post: Optional[Callable[..., Any]] = None,
) -> ToolResult:
    """Execute a single-query Tavily web search via SearchService.

    `single_query` is retained in signature for transitional compatibility,
    but `SearchService` unconditionally executes at most 1 query per call.
    """
    _ = single_query
    return search_web(
        query=query,
        max_results=max_results,
        api_key=api_key,
        http_post=http_post,
    )


def is_blacklisted_recipient(recipient: str) -> tuple[bool, str]:
    blacklist_raw = os.getenv("BLACKLIST_DOMAINS", "investor.com,board.com,vip.com,internal.com")
    blocked_items = [b.strip().lower() for b in blacklist_raw.split(",") if b.strip()]
    rec_lower = (recipient or "").strip().lower()
    for b in blocked_items:
        if b in rec_lower:
            return True, f"Blocked by VIP Blacklist Guardrail: Recipient '{recipient}' matches restricted filter '{b}'"
    return False, ""


def execute_email_sender(to: str, subject: str, body: str) -> ToolResult:
    started_at = _utc_now()
    blocked, reason = is_blacklisted_recipient(to)
    if blocked:
        return ToolResult.blocked(
            tool_id="email_sender",
            error_code="BLACKLIST_BLOCKED",
            error_message=reason,
            data={
                "status": "blocked_by_guardrail",
                "reason": reason,
                "recipient": to,
                "timestamp": _utc_now(),
            },
            started_at=started_at,
            completed_at=_utc_now(),
        )

    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_pass = (os.getenv("SMTP_PASS") or "").strip()

    if smtp_user and smtp_pass:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = subject
            msg["From"] = f"AI Employee <{smtp_user}>"
            msg["To"] = to

            escaped_body = html.escape(body or "").replace("\n", "<br>")
            escaped_sender = html.escape(smtp_user)
            part1 = MIMEText(body or "", "plain", "utf-8")
            html_body = (
                '<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">'
                f"<p>{escaped_body}</p>"
                '<hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">'
                f'<p style="font-size: 11px; color: #888;">Dispatched autonomously via Webshastraa AI Employee Platform &bull; Sender: {escaped_sender}</p>'
                "</div>"
            )
            part2 = MIMEText(html_body, "html", "utf-8")
            msg.attach(part1)
            msg.attach(part2)

            with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, [to], msg.as_string())

            return ToolResult.ok(
                tool_id="email_sender",
                data={
                    "status": "sent_via_gmail_smtp",
                    "sender": smtp_user,
                    "recipient": to,
                    "subject": subject,
                    "timestamp": _utc_now(),
                },
                started_at=started_at,
                completed_at=_utc_now(),
            )
        except Exception as exc:
            return ToolResult.fail(
                tool_id="email_sender",
                error_code="SMTP_ERROR",
                error_message=str(exc),
                data={
                    "status": "smtp_error",
                    "error": str(exc),
                    "recipient": to,
                    "preview": (body or "")[:120],
                },
                started_at=started_at,
                completed_at=_utc_now(),
            )

    return ToolResult.ok(
        tool_id="email_sender",
        data={
            "status": "simulated_mail_gateway",
            "recipient": to,
            "subject": subject,
            "preview": (body or "")[:120] + "...",
            "timestamp": _utc_now(),
        },
        started_at=started_at,
        completed_at=_utc_now(),
    )


def execute_sheet_logger(table: str, record: Dict[str, Any]) -> ToolResult:
    started_at = _utc_now()
    safe_table = re.sub(r"[^a-zA-Z0-9_-]", "_", (table or "general_records").strip()) or "general_records"
    csv_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
    os.makedirs(csv_dir, exist_ok=True)
    csv_file = os.path.join(csv_dir, f"{safe_table}.csv")

    try:
        file_exists = os.path.isfile(csv_file)
        safe_record = record if isinstance(record, dict) else {"value": str(record)}
        with open(csv_file, mode="a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["timestamp"] + list(safe_record.keys()))
            if not file_exists:
                writer.writeheader()
            row = {"timestamp": _utc_now(), **safe_record}
            writer.writerow(row)

        return ToolResult.ok(
            tool_id="sheet_logger",
            data={"status": "recorded", "table": safe_table, "file": csv_file, "rows_added": 1},
            started_at=started_at,
            completed_at=_utc_now(),
        )
    except Exception as exc:
        return ToolResult.fail(
            tool_id="sheet_logger",
            error_code="SHEET_WRITE_ERROR",
            error_message=str(exc),
            data={"table": safe_table},
            started_at=started_at,
            completed_at=_utc_now(),
        )


def execute_slack_notifier(channel: str, message: str) -> ToolResult:
    started_at = _utc_now()
    slack_webhook = (os.getenv("SLACK_WEBHOOK_URL") or "").strip()
    if slack_webhook:
        try:
            resp = requests.post(slack_webhook, json={"text": f"[{channel}] {message}"}, timeout=5)
            resp.raise_for_status()
            return ToolResult.ok(
                tool_id="slack_notifier",
                data={"status": "posted", "destination": "slack", "channel": channel},
                started_at=started_at,
                completed_at=_utc_now(),
            )
        except Exception as exc:
            return ToolResult.fail(
                tool_id="slack_notifier",
                error_code="SLACK_WEBHOOK_ERROR",
                error_message=str(exc),
                data={"channel": channel, "preview": (message or "")[:100]},
                started_at=started_at,
                completed_at=_utc_now(),
            )

    return ToolResult.ok(
        tool_id="slack_notifier",
        data={"status": "logged", "channel": channel, "preview": (message or "")[:100]},
        started_at=started_at,
        completed_at=_utc_now(),
    )


def execute_domain_verifier(url: str) -> ToolResult:
    started_at = _utc_now()
    try:
        from app.services.domain_verifier import verify_domain_safely
        res = verify_domain_safely(url)
        if res.error_code == "HTTP_TIMEOUT":
            return ToolResult.timeout(
                tool_id="domain_verifier",
                error_code=res.error_code,
                error_message=res.error_detail or "Domain verification timed out.",
                data=res.model_dump(),
                started_at=started_at,
                completed_at=_utc_now(),
            )
        if res.error_code == "SSRF_BLOCKED":
            return ToolResult.blocked(
                tool_id="domain_verifier",
                error_code=res.error_code,
                error_message=res.error_detail or "Blocked by SSRF guard.",
                data=res.model_dump(),
                started_at=started_at,
                completed_at=_utc_now(),
            )
        return ToolResult.ok(
            tool_id="domain_verifier",
            data=res.model_dump(),
            started_at=started_at,
            completed_at=_utc_now(),
        )
    except Exception as exc:
        return ToolResult.fail(
            tool_id="domain_verifier",
            error_code="VERIFIER_ERROR",
            error_message=str(exc),
            data={"url": url},
            started_at=started_at,
            completed_at=_utc_now(),
        )


def execute_tool_call(tool_name: str, tool_params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Dispatch a registered tool by ID and return its ToolResult payload dict."""
    params = tool_params or {}
    normalized = (tool_name or "").strip().lower()
    if normalized == "web_search":
        res = execute_web_search(query=str(params.get("query", "")))
    elif normalized == "email_sender":
        res = execute_email_sender(
            to=str(params.get("to", "")),
            subject=str(params.get("subject", "Update from AI Employee")),
            body=str(params.get("body", "")),
        )
    elif normalized == "sheet_logger":
        res = execute_sheet_logger(
            table=str(params.get("table", "general_records")),
            record=params.get("record") if isinstance(params.get("record"), dict) else {},
        )
    elif normalized == "slack_notifier":
        res = execute_slack_notifier(
            channel=str(params.get("channel", "#general")),
            message=str(params.get("message", "")),
        )
    elif normalized == "domain_verifier":
        res = execute_domain_verifier(url=str(params.get("url", "")))
    else:
        return {"error": f"Unknown tool '{tool_name}' invoked"}

    return res.model_dump() if hasattr(res, "model_dump") else dict(res)

