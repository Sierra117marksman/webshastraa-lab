"""
Deterministic Lead Verification & Qualification Engine (v1)
Enforces machine-enforced qualification:
- Field-level evidence binding (Evidence, LeadField, VerifiedLead)
- Strict Tri-State semantics: VERIFIED / PROSPECT / REJECTED
- Source-to-claim integrity checker (rejects generic blogs as proof for private revenue/performance)
- Deterministic outreach claim validator (blocks/sanitizes unmeasured speed/bounce claims)
"""

from __future__ import annotations
import re
from datetime import datetime
from typing import List, Dict, Any, Optional, Literal
from pydantic import BaseModel, Field

# Generic marketing/news domains that CANNOT support company-specific private financials or load speed
GENERIC_ARTICLE_DOMAINS = [
    'vcwire.tech',
    'projectsupply.in',
    'echai.ventures',
    'c4e.in',
    'cre8ivemarketing.in',
    'thed2cpulse.com',
    'behaf.co',
    'inc42.com',
    'yourstory.com',
    'medium.com',
    'linkedin.com/posts'
]


class Evidence(BaseModel):
    source_url: str
    source_type: str  # 'live_storefront', 'storeleads_directory', 'annual_filing', 'job_board', 'article'
    supports_field: str  # 'platform', 'apps', 'revenue', 'website_observation', 'contact'
    retrieved_at: str = Field(default_factory=lambda: datetime.utcnow().isoformat())
    evidence_summary: str


class LeadField(BaseModel):
    value: Optional[str] = None
    status: Literal["VERIFIED", "UNVERIFIED", "NOT_AUDITED"] = "UNVERIFIED"
    evidence: List[Evidence] = Field(default_factory=list)


class VerifiedLead(BaseModel):
    company_name: str
    website: str
    platform: LeadField
    apps: LeadField
    revenue: LeadField
    website_observation: LeadField
    contact: LeadField
    lead_status: Literal["VERIFIED", "PROSPECT", "REJECTED"] = "PROSPECT"
    qualification_notes: List[str] = Field(default_factory=list)


class QualificationEngine:
    @staticmethod
    def validate_source_claim_integrity(field_name: str, evidence: Evidence) -> tuple[bool, str]:
        """
        Hard rule: The cited source must directly establish the specific claim.
        A generic article/blog cannot establish private company revenue or unmeasured load times.
        """
        source_lower = (evidence.source_url or '').lower()
        for bad_domain in GENERIC_ARTICLE_DOMAINS:
            if bad_domain in source_lower:
                if field_name in ('revenue', 'website_observation'):
                    return False, f"Source '{bad_domain}' is a generic publication and cannot verify private '{field_name}'."
        return True, ""

    @classmethod
    def qualify_lead(
        cls,
        lead: VerifiedLead,
        hard_constraints: Optional[List[str]] = None,
        is_reachable: bool = True,
        detected_platform: Optional[str] = None
    ) -> VerifiedLead:
        """
        Applies deterministic machine-enforced qualification:
        1. Checks site reachability. Dead/unreachable domains are marked REJECTED.
        2. Validates source integrity on all fields. Invalid sources drop field to UNVERIFIED.
        3. Checks for platform contradiction (e.g. required Shopify but site is WooCommerce).
        4. Enforces Tri-State status based on hard constraints.
        """
        notes = []

        # 1. Reachability Check
        if not is_reachable:
            lead.lead_status = "REJECTED"
            lead.qualification_notes.append("Domain is dead or unreachable via SSRF-safe HTTP inspection.")
            return lead

        # 2. Source-to-claim integrity validation for every field
        fields_to_check = [
            ('platform', lead.platform),
            ('apps', lead.apps),
            ('revenue', lead.revenue),
            ('website_observation', lead.website_observation),
            ('contact', lead.contact)
        ]

        for name, field in fields_to_check:
            valid_evidence = []
            for ev in field.evidence:
                is_valid, reason = cls.validate_source_claim_integrity(name, ev)
                if is_valid:
                    valid_evidence.append(ev)
                else:
                    notes.append(f"Rejected invalid evidence for {name}: {reason}")
            
            field.evidence = valid_evidence
            if not valid_evidence and field.status == "VERIFIED":
                field.status = "UNVERIFIED"
                notes.append(f"Field '{name}' downgraded from VERIFIED to UNVERIFIED due to lack of primary supporting evidence.")

        # 3. Contradictory Platform Check
        if detected_platform and detected_platform != "UNKNOWN":
            lead_platform_val = (lead.platform.value or '').lower()
            det_lower = detected_platform.lower()
            if lead_platform_val and det_lower not in lead_platform_val and lead_platform_val not in det_lower:
                lead.lead_status = "REJECTED"
                lead.qualification_notes.append(
                    f"Platform contradiction: Stated '{lead.platform.value}' but live audit detected '{detected_platform}'."
                )
                return lead

        # 4. Enforce Hard Constraints for Tri-State Status
        # Default hard constraints if not provided: ['platform', 'website']
        active_constraints = hard_constraints or ['platform']
        
        all_hard_verified = True
        for hc in active_constraints:
            field_obj = getattr(lead, hc, None)
            if field_obj is None or field_obj.status != "VERIFIED":
                all_hard_verified = False
                notes.append(f"Hard constraint '{hc}' remains {getattr(field_obj, 'status', 'UNVERIFIED')}.")

        if all_hard_verified:
            lead.lead_status = "VERIFIED"
        else:
            # If the business is real but some hard constraints (e.g. private revenue) are unverified:
            lead.lead_status = "PROSPECT"

        lead.qualification_notes.extend(notes)
        return lead


class OutreachClaimValidator:
    """
    Scans outreach emails for unverified or hallucinated performance/financial claims.
    Blocks or sanitizes claims into safe, consultative audit phrasing.
    """
    # Regex detecting unmeasured performance numbers like "3.5s", "4.8 seconds", "22% bounce"
    UNMEASURED_LOAD_REGEX = re.compile(
        r'\b(?:\d+(?:\.\d+)?\s*(?:s|sec|seconds?)|load(?:s|ed|ing)?\s+(?:in|taking)\s+\d+(?:\.\d+)?\s*(?:s|sec|seconds?))\b',
        re.IGNORECASE
    )
    UNMEASURED_BOUNCE_REGEX = re.compile(
        r'\b\d+(?:\.\d+)?%\s*(?:bounce|drop-off|abandonment)\b',
        re.IGNORECASE
    )

    @classmethod
    def validate_and_sanitize_outreach(cls, text: str, lead: VerifiedLead) -> tuple[str, bool, List[str]]:
        """
        Validates outreach text against lead evidence.
        If unmeasured speed/bounce claims exist and lead.website_observation is NOT VERIFIED:
        Replaces with safe consultative wording: 'several areas I would like to audit for mobile conversion and checkout speed'.
        Returns (sanitized_text, was_modified, violations).
        """
        violations = []
        sanitized = text
        was_modified = False

        is_perf_verified = (lead.website_observation.status == "VERIFIED")

        if not is_perf_verified:
            # Check for specific unmeasured load time claims
            if cls.UNMEASURED_LOAD_REGEX.search(sanitized):
                violations.append("Contained unmeasured load time claim (e.g. '3.5s', '4.8s') without verified tool audit.")
                sanitized = cls.UNMEASURED_LOAD_REGEX.sub("several mobile performance bottlenecks", sanitized)
                was_modified = True

            # Check for specific unmeasured bounce/abandonment percentages
            if cls.UNMEASURED_BOUNCE_REGEX.search(sanitized):
                violations.append("Contained unmeasured bounce/abandonment percentage without verified data.")
                sanitized = cls.UNMEASURED_BOUNCE_REGEX.sub("friction in the checkout funnel", sanitized)
                was_modified = True

        return sanitized, was_modified, violations
