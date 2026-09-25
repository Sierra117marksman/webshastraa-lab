"""
Reflection Engine — Phase 1

Converts task failures and founder rejections into proposed MemoryRecords
that go through the Memory Approval Layer before becoming active rules.

Uses Groq (llama-3.3-70b) for fast, cheap reflection generation.
Falls back to a structured heuristic if Groq is unavailable.
"""

from __future__ import annotations
import os
import uuid
import json
from datetime import datetime
from typing import Optional

from app.models.memory import MemoryRecord, MemoryCategory, MemoryTrigger


def _call_groq(prompt: str) -> Optional[str]:
    try:
        from groq import Groq
        key = os.getenv("GROQ_API_KEY", "")
        if not key.strip():
            return None
        client = Groq(api_key=key)
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=512,
        )
        return response.choices[0].message.content.strip()
    except Exception:
        return None


REFLECTION_PROMPT = """You are a management consultant analyzing an AI employee's task failure or rejected action.

EMPLOYEE: {name}
ROLE: {role}
TASK: {task_prompt}
WHAT HAPPENED: {what_happened}
FOUNDER FEEDBACK: {feedback}

Your job: Extract a single, precise, actionable rule that this employee should follow in the future to avoid repeating this failure.

Respond in this exact JSON format (no other text):
{{
  "title": "<short label, max 8 words>",
  "category": "<one of: mistake_avoided | learned_rule | proven_playbook | founder_preference>",
  "scope": "<one of: global | cold_outreach | enterprise_clients | follow_up_emails | data_research | financial_ops | content_creation>",
  "context": "<1-2 sentences: what was the task and what went wrong>",
  "critique": "<1-2 sentences: root cause of the failure>",
  "distilled_rule": "<imperative instruction starting with a verb, max 2 sentences>",
  "confidence_score": <float 0.0-1.0 based on clarity of the feedback>,
  "priority": <integer 1-5 where 1 is most critical>
}}"""


def _heuristic_reflect(
    employee_name: str,
    employee_role: str,
    task_prompt: str,
    what_happened: str,
    feedback: str,
) -> dict:
    """Fallback heuristic reflection when Groq is unavailable."""
    has_clear_rule = len(feedback) > 40
    return {
        "title": f"Rule from: {task_prompt[:40]}",
        "category": "mistake_avoided",
        "scope": "global",
        "context": f"Task: {task_prompt[:120]}. Result: {what_happened[:120]}",
        "critique": f"Founder feedback: {feedback[:200]}",
        "distilled_rule": feedback[:300] if has_clear_rule else f"Review this task pattern carefully: {task_prompt[:100]}",
        "confidence_score": 0.6 if has_clear_rule else 0.3,
        "priority": 2 if has_clear_rule else 4,
    }


def generate_proposed_memory(
    employee_id: str,
    employee_name: str,
    employee_role: str,
    task_id: str,
    task_prompt: str,
    what_happened: str,
    feedback: str,
    trigger_event: MemoryTrigger = "rejection",
) -> Optional[MemoryRecord]:
    """
    Generate a proposed MemoryRecord from a task failure or rejection.

    Returns a MemoryRecord with status='proposed'.
    Returns None if the feedback is too sparse to form a useful rule
    (confidence_score < 0.25 after Groq attempt).

    The caller must save this to the DB — this function does not persist.
    """
    if not feedback or not feedback.strip():
        return None

    # Attempt Groq-powered reflection
    prompt = REFLECTION_PROMPT.format(
        name=employee_name,
        role=employee_role,
        task_prompt=task_prompt,
        what_happened=what_happened,
        feedback=feedback,
    )

    raw = _call_groq(prompt)
    reflection: Optional[dict] = None

    if raw:
        # Parse JSON from Groq response
        try:
            clean = raw.strip()
            start = clean.find("{")
            end = clean.rfind("}")
            if start != -1 and end != -1:
                reflection = json.loads(clean[start : end + 1])
        except Exception:
            pass

    if not reflection:
        reflection = _heuristic_reflect(
            employee_name, employee_role, task_prompt, what_happened, feedback
        )

    # Don't create a memory if it's too vague
    if reflection.get("confidence_score", 0) < 0.25:
        return None

    now = datetime.utcnow().isoformat()

    # Validate category (Groq may hallucinate an invalid one)
    valid_categories: list[MemoryCategory] = [
        "mistake_avoided", "learned_rule", "proven_playbook", "founder_preference"
    ]
    category = reflection.get("category", "mistake_avoided")
    if category not in valid_categories:
        category = "mistake_avoided"

    return MemoryRecord(
        id=f"mem_{uuid.uuid4().hex[:12]}",
        employee_id=employee_id,
        category=category,  # type: ignore[arg-type]
        title=reflection.get("title", "Untitled learning")[:100],
        trigger_event=trigger_event,
        scope=reflection.get("scope", "global"),
        source=f"Auto-reflection on task {task_id}",
        context=reflection.get("context", "")[:500],
        critique=reflection.get("critique", "")[:500],
        distilled_rule=reflection.get("distilled_rule", feedback[:300]),
        confidence_score=min(1.0, max(0.0, float(reflection.get("confidence_score", 0.5)))),
        priority=max(1, min(5, int(reflection.get("priority", 3)))),
        version=1,
        status="proposed",
        created_at=now,
    )
