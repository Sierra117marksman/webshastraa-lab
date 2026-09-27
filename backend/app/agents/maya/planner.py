"""Maya Planner — LLMGateway.call() → Pydantic validation → fail-closed Requirement normalization.

Key invariants (Rev 3):
- observability_class is enforced by the Requirement model_validator, never trusted from LLM output
- on_unknown is forced to PROSPECT for LOW_PUBLIC_OBSERVABILITY fields (revenue, paid_app_subscription, performance_audit)
- Installed app script detection (`installed_apps`, HIGH observability) is separated from
  paid app billing tier (`paid_app_subscription`, LOW_PUBLIC_OBSERVABILITY)
- Unknown RequirementField literals are dropped rather than passed downstream
- Persists normalized Requirement rows into SQLite `session_requirements`
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, ValidationError

from app.agents.schemas.requirement import (
    LOW_OBSERVABILITY_FIELDS,
    Requirement,
    RequirementField,
    RequirementOperator,
    RequirementPriority,
    UnknownPolicy,
)
from app.agents.schemas.session import ResearchSession
from app.db.connection import DB_PATH, transaction
from app.engine.llm_gateway import LLMGateway, LLMGatewayError

logger = logging.getLogger(__name__)

_VALID_FIELDS: set[str] = set(RequirementField.__args__)  # type: ignore[attr-defined]


class _RawRequirement(BaseModel):
    field: str
    operator: str = "equals"
    expected: Any = ""
    priority: str = "HARD"
    on_unknown: str = "REJECT"
    observability_class: Optional[str] = None


class _PlanSchema(BaseModel):
    """Raw plan from LLM — validated loosely then normalized fail-closed in Python."""
    search_queries: List[str] = Field(default_factory=list)
    requirements: List[_RawRequirement] = Field(default_factory=list)
    target_verified_leads: int = Field(default=10, ge=1)
    max_hops: int = Field(default=4, ge=1)
    notes: Optional[str] = None


def _normalize_raw_requirement(
    raw: _RawRequirement,
    session_id: str,
) -> Optional[Requirement]:
    """Convert a raw LLM requirement into a fail-closed Requirement, or return None to drop it."""
    field_str = (raw.field or "").strip().lower()
    if field_str == "apps":
        field_str = "installed_apps"
    elif field_str in ("website_condition", "speed"):
        field_str = "performance_audit"

    if field_str not in _VALID_FIELDS:
        logger.warning(
            "[Planner] Dropping unknown requirement field '%s' from LLM plan", field_str
        )
        return None

    operator: RequirementOperator = (
        raw.operator if raw.operator in RequirementOperator.__args__ else "equals"  # type: ignore[attr-defined]
    )
    priority: RequirementPriority = (
        raw.priority.upper() if isinstance(raw.priority, str) and raw.priority.upper() in ("HARD", "SOFT") else "HARD"  # type: ignore[assignment]
    )
    on_unknown: UnknownPolicy = (
        raw.on_unknown.upper() if isinstance(raw.on_unknown, str) and raw.on_unknown.upper() in ("REJECT", "PROSPECT") else "REJECT"  # type: ignore[assignment]
    )

    try:
        # Note: we intentionally do NOT trust raw.observability_class for low-observability fields.
        # Requirement's @model_validator enforces LOW_PUBLIC_OBSERVABILITY and on_unknown='PROSPECT'
        # for revenue, paid_app_subscription, and performance_audit.
        req = Requirement(
            session_id=session_id,
            field=field_str,  # type: ignore[arg-type]
            operator=operator,
            expected=raw.expected if raw.expected is not None else "",
            priority=priority,
            on_unknown=on_unknown,
        )
    except (ValidationError, ValueError) as exc:
        logger.warning("[Planner] Dropping invalid requirement (field=%s): %s", field_str, exc)
        return None

    return req


def _extract_deterministic_requirements(task_prompt: str, session_id: str) -> List[Requirement]:
    """Deterministic requirement extractor ensuring core constraints are always captured."""
    lower = (task_prompt or "").lower()
    reqs: List[Requirement] = []

    has_shopify = "shopify" in lower
    has_woo = "woocommerce" in lower
    is_dual_contradictory = (
        has_shopify
        and has_woo
        and any(w in lower for w in ("both ", "simultaneously", "and also run woocommerce", "that also run woocommerce"))
    )
    if is_dual_contradictory:
        reqs.append(
            Requirement(
                session_id=session_id,
                field="platform",
                operator="equals",
                expected="Shopify",
                priority="HARD",
                on_unknown="REJECT",
            )
        )
        reqs.append(
            Requirement(
                session_id=session_id,
                field="platform",
                operator="equals",
                expected="WooCommerce",
                priority="HARD",
                on_unknown="REJECT",
            )
        )
    elif has_shopify and has_woo and " or " in lower:
        reqs.append(
            Requirement(
                session_id=session_id,
                field="platform",
                operator="in",
                expected=["Shopify", "WooCommerce"],
                priority="HARD",
                on_unknown="REJECT",
            )
        )
    elif has_shopify:
        reqs.append(
            Requirement(
                session_id=session_id,
                field="platform",
                operator="equals",
                expected="Shopify",
                priority="HARD",
                on_unknown="REJECT",
            )
        )
    elif has_woo:
        reqs.append(
            Requirement(
                session_id=session_id,
                field="platform",
                operator="equals",
                expected="WooCommerce",
                priority="HARD",
                on_unknown="REJECT",
            )
        )

    if any(k in lower for k in ["app", "apps", "wati", "nudgify", "loox", "judge.me", "klaviyo"]):
        reqs.append(
            Requirement(
                session_id=session_id,
                field="installed_apps",
                operator="exists",
                expected=True,
                priority="HARD",
                on_unknown="PROSPECT",
            )
        )

    if any(
        k in lower
        for k in [
            "paying in app",
            "paid app",
            "paid subscription",
            "paying for ",
            "paid plan",
            "paid tier",
            "app subscription",
        ]
    ):
        reqs.append(
            Requirement(
                session_id=session_id,
                field="paid_app_subscription",
                operator="exists",
                expected=True,
                priority="HARD",
                on_unknown="PROSPECT",
            )
        )

    if any(k in lower for k in ["turnover", "revenue", "lakh", "crore", "arr", "mrr"]):
        from app.agents.schemas.requirement import NumericRange
        reqs.append(
            Requirement(
                session_id=session_id,
                field="revenue",
                operator="range",
                expected=NumericRange(min_value=1000000, max_value=5000000, currency="INR"),
                priority="HARD",
                on_unknown="PROSPECT",
            )
        )

    if any(k in lower for k in ["old", "crappy", "slow", "speed", "load time", "performance"]):
        reqs.append(
            Requirement(
                session_id=session_id,
                field="performance_audit",
                operator="exists",
                expected=True,
                priority="SOFT",
                on_unknown="PROSPECT",
            )
        )

    return reqs


class PlanResult:
    """Structured output of a planning call."""

    def __init__(
        self,
        search_queries: List[str],
        requirements: List[Requirement],
        target_verified_leads: int,
        max_hops: int,
        notes: Optional[str] = None,
        observability_notices: Optional[List[str]] = None,
    ) -> None:
        self.search_queries = search_queries
        self.requirements = requirements
        self.target_verified_leads = target_verified_leads
        self.max_hops = max_hops
        self.notes = notes
        self.observability_notices = observability_notices or []


class MayaPlanner:
    """Structured research plan generator with fail-closed requirement normalization."""

    SYSTEM_PROMPT = (
        "You are a structured research planner for an autonomous B2B lead discovery agent. "
        "Given a task prompt, produce a structured research plan with diverse search queries, "
        "explicit data requirements, and a realistic target. "
        "Requirements must use only these field names: "
        "platform, installed_apps, paid_app_subscription, d2c_status, revenue, "
        "technical_observables, performance_audit, geography, storefront_state, contact, hiring_role. "
        "For revenue, paid_app_subscription, and performance_audit, always set on_unknown='PROSPECT' "
        "since these are LOW_PUBLIC_OBSERVABILITY metrics not publicly verifiable from storefront HTML. "
        "Respond ONLY with a valid JSON object matching the required schema."
    )

    def __init__(self, gateway: Optional[LLMGateway] = None, db_path: Optional[str] = None) -> None:
        self._gateway = gateway or LLMGateway()
        self._explicit_db_path = db_path


    @property
    def _db_path(self) -> str:
        import app.db.connection as _conn_mod
        return self._explicit_db_path or _conn_mod.DB_PATH


    def plan(self, task_prompt: str, session_id: str, persist: bool = True) -> PlanResult:
        """Generate, normalize, and optionally persist a fail-closed PlanResult."""
        count_match = re.search(
            r"\b(\d{1,2})\s+(?:[\w\-]+\s+){0,6}?(?:business|businesses|brand|brands|store|stores|lead|leads|prospect|prospects|compan)",
            (task_prompt or "").lower(),
        )
        default_target = int(count_match.group(1)) if count_match else 10
        default_target = max(1, min(default_target, 20))

        raw_plan: Optional[_PlanSchema] = None
        try:
            result = self._gateway.call(
                contents=[{"role": "user", "content": task_prompt}],
                system_prompt=self.SYSTEM_PROMPT,
                response_schema=_PlanSchema,
            )
            raw_plan = result.parsed_result  # type: ignore[assignment]
        except LLMGatewayError as exc:
            logger.warning("[Planner] LLMGateway call failed (%s); falling back to deterministic plan.", exc)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Planner] Unexpected LLM error (%s); falling back to deterministic plan.", exc)

        requirements: List[Requirement] = []
        queries: List[str] = []
        target = default_target
        max_hops = 4
        notes: Optional[str] = None

        if raw_plan is not None:
            queries = [q.strip() for q in (raw_plan.search_queries or []) if q and q.strip()]
            for raw_req in raw_plan.requirements or []:
                req = _normalize_raw_requirement(raw_req, session_id)
                if req is not None:
                    requirements.append(req)
            target = max(1, min(raw_plan.target_verified_leads or default_target, 25))
            max_hops = max(1, min(raw_plan.max_hops or 4, 8))
            notes = raw_plan.notes

        # Merge deterministic requirements for any key constraint the LLM omitted
        existing_fields = {r.field for r in requirements}
        existing_pairs = {(r.field, str(r.expected).lower()) for r in requirements}
        det_reqs = _extract_deterministic_requirements(task_prompt, session_id)
        platform_det_count = sum(1 for r in det_reqs if r.field == "platform")
        for det_req in det_reqs:
            pair = (det_req.field, str(det_req.expected).lower())
            if det_req.field == "platform" and platform_det_count > 1:
                if pair not in existing_pairs:
                    requirements.append(det_req)
                    existing_pairs.add(pair)
                    existing_fields.add(det_req.field)
            elif det_req.field not in existing_fields:
                requirements.append(det_req)
                existing_fields.add(det_req.field)
                existing_pairs.add(pair)

        if not queries and (task_prompt or "").strip():
            queries = self.generate_hop_queries_for_prompt(task_prompt, hop=1)

        observability_notices: List[str] = []
        for req in requirements:
            if req.observability_class == "LOW_PUBLIC_OBSERVABILITY" or req.field in LOW_OBSERVABILITY_FIELDS:
                observability_notices.append(
                    f"Requirement '{req.field}' has LOW_PUBLIC_OBSERVABILITY; "
                    f"when unverified from authoritative filings, qualifying leads become PROSPECT."
                )

        if persist and requirements:
            self.persist_requirements(session_id, requirements)

        return PlanResult(
            search_queries=queries,
            requirements=requirements,
            target_verified_leads=target,
            max_hops=max_hops,
            notes=notes,
            observability_notices=observability_notices,
        )

    def persist_requirements(self, session_id: str, requirements: List[Requirement]) -> None:
        """Persist normalized Requirement rows into SQLite `session_requirements`."""
        try:
            with transaction(self._db_path) as conn:
                for req in requirements:
                    exp_val = req.expected.model_dump() if hasattr(req.expected, "model_dump") else req.expected
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO session_requirements (
                            id, session_id, field, operator, expected_json,
                            priority, on_unknown, observability_class,
                            evidence_required, allowed_source_types_json
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            req.id,
                            session_id,
                            req.field,
                            req.operator,
                            json.dumps(exp_val),
                            req.priority,
                            req.on_unknown,
                            req.observability_class,
                            1 if req.evidence_required else 0,
                            json.dumps(list(req.allowed_source_types or [])),
                        ),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[Planner] Failed to persist session_requirements: %s", exc)


    @staticmethod
    def generate_hop_queries_for_prompt(task_prompt: str, hop: int) -> List[str]:
        """Generate distinct, non-overlapping search queries per hop."""
        lower = (task_prompt or "").lower()
        platform = "WooCommerce" if "woocommerce" in lower else "Shopify"
        geo = "India" if any(k in lower for k in ["india", "indian", "lakh", "₹"]) else ""
        raw = (task_prompt or "").strip()[:100]

        if hop == 1:
            return [
                f'site:storeleads.app "country/IN" "{platform}" "Wati" OR "Nudgify" OR "Fera"',
                f"{geo} D2C {platform} brands stores using apps".strip(),
            ]
        if hop == 2:
            return [
                f'site:storeleads.app "country/IN" "Judge.me" OR "Loox" OR "Smile.io" OR "Easysize"',
                f'site:myshopify.com "{geo or "D2C"}" skincare fashion store',
            ]
        if hop == 3:
            return [
                f'site:storeleads.app "reports/shopify/IN" "Domain" "Rank"',
                f'"{platform}" D2C brands {geo} official store ".in" OR ".com" shopping'.strip(),
            ]
        return [
            f"{raw} official website store".strip(),
            f"emerging D2C ecommerce brands {geo} {platform} store directory".strip(),
        ]

    @classmethod
    def generate_hop_queries(cls, session: ResearchSession, hop: int) -> List[str]:
        """Return fresh queries for `hop` that have not yet been used in `session`."""
        candidates = cls.generate_hop_queries_for_prompt(session.raw_prompt, hop)
        used = set(session.search_queries_used or [])
        fresh = [q for q in candidates if q and q not in used]
        if fresh:
            session.search_queries_used.extend(fresh)
        return fresh
