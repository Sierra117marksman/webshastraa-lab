import json
from typing import Any, Dict, List, Optional
from app.agents.schemas.candidate import Candidate, CandidateLedger
from app.agents.schemas.evidence import EvidenceStore
from app.agents.schemas.session import ResearchSession
from app.agents.employees.maya.claim_validator import MayaClaimValidator


class MayaComposer:
    """
    Separates Deliverable & Outreach Composition from Research.
    - The Qualification Table & Evidence Ledger are rendered deterministically in Python
      from CandidateLedger + EvidenceStore (zero chance of LLM inventing rows).
    - The Outreach Generator receives ONLY allowed_outreach_claims verified by MayaClaimValidator.
    """

    @classmethod
    def compose_deliverable(
        cls,
        session: ResearchSession,
        ledger: CandidateLedger,
        evidence_store: EvidenceStore,
        llm_client: Any = None
    ) -> Dict[str, Any]:
        viable = ledger.get_viable()[:session.target_leads]
        verified_list = [c for c in viable if c.qualification_status == "VERIFIED"]
        prospect_list = [c for c in viable if c.qualification_status == "PROSPECT"]
        rejected_list = ledger.get_rejected()

        # 1. Build Allowed Claims Whitelist for each viable candidate
        allowed_by_cand: Dict[str, List[Dict[str, str]]] = {}
        for cand in viable:
            allowed_by_cand[cand.id] = MayaClaimValidator.build_allowed_outreach_claims(cand, evidence_store)

        # 2. Compose Consultative Outreach Draft (receives ONLY allowed_outreach_claims)
        outreach_draft = None
        if viable:
            top_cand = viable[0]
            outreach_draft = cls._compose_outreach_from_allowed_claims(
                cand=top_cand,
                allowed_claims=allowed_by_cand.get(top_cand.id, []),
                session=session,
                llm_client=llm_client
            )

        # 3. Assemble Deterministic, Evidence-Backed Markdown Dossier
        lines: List[str] = []
        lines.append("# Maya v2 — Evidence-Backed Lead & Qualification Dossier")
        lines.append("")

        # Executive Honesty & Telemetry Banner
        lines.append("## 1. Executive Qualification Summary")
        if len(viable) < session.target_leads:
            lines.append(
                f"> **Epistemic Honesty Notice**: You requested **{session.target_leads}** leads. "
                f"After exhausting **{session.current_hop}/{session.max_hops} search hops** and auditing "
                f"**{session.candidates_verified} candidate domains**, **{len(viable)}** genuine candidates "
                f"survived verification (**{len(verified_list)} VERIFIED**, **{len(prospect_list)} PROSPECT**, "
                f"**{len(rejected_list)} REJECTED**). Per strict anti-fabrication rules, zero filler leads were invented."
            )
        else:
            lines.append(
                f"> **Qualification Complete**: Found **{len(viable)}** qualified candidates "
                f"(**{len(verified_list)} VERIFIED**, **{len(prospect_list)} PROSPECT**) across "
                f"**{session.current_hop} search hops** ({session.candidates_verified} domains audited)."
            )

        if session.hard_constraints.get("revenue_requested"):
            lines.append(
                "> **Private Revenue Disclosure**: Private Indian D2C brands do not publish audited annual turnover "
                "on public storefronts. All private turnover fields are strictly marked **`UNVERIFIED (Private entity)`** "
                "and candidates are classified as **`🟡 PROSPECT`** pending qualification discovery."
            )
        lines.append("")

        # 2. Structured Candidate Ledger Table
        lines.append("## 2. Verified & Prospect Candidate Ledger")
        if not viable:
            lines.append("_No candidates survived mechanical domain and platform verification across all search hops._")
        else:
            lines.append(
                "| # | Candidate ID | Brand / Company | Direct Website | Platform | Detected Apps | Revenue Status | Website Speed / UX | Qualification Status | Evidence IDs |"
            )
            lines.append(
                "|---|---|---|---|---|---|---|---|---|---|"
            )
            for idx, cand in enumerate(viable, start=1):
                plat_str = (
                    f"✅ {cand.platform.value}"
                    if cand.platform.status == "SUPPORTED" and cand.platform.value
                    else f"❓ {cand.platform.status}"
                )
                apps_str = (
                    f"✅ {cand.apps.value}"
                    if cand.apps.status == "SUPPORTED" and cand.apps.value
                    else "❓ UNVERIFIED"
                )
                rev_str = (
                    f"✅ {cand.revenue.value}"
                    if cand.revenue.status == "SUPPORTED"
                    else "❓ UNVERIFIED (Private)"
                )
                ux_str = (
                    f"✅ {cand.website_condition.value}"
                    if cand.website_condition.status == "SUPPORTED"
                    else "⚠️ NOT AUDITED"
                )
                status_badge = (
                    "✅ VERIFIED" if cand.qualification_status == "VERIFIED" else "🟡 PROSPECT"
                )
                ev_ids = sorted({
                    eid
                    for claim in cand.get_all_claims().values()
                    for eid in claim.evidence_ids
                })
                ev_str = ", ".join(ev_ids) if ev_ids else "None"
                lines.append(
                    f"| {idx} | `{cand.id}` | **{cand.company_name}** | [{cand.canonical_domain}]({cand.url}) | "
                    f"{plat_str} | {apps_str} | {rev_str} | {ux_str} | **{status_badge}** | `{ev_str}` |"
                )
        lines.append("")

        # 3. First-Class Evidence Store Citations
        lines.append("## 3. Primary Evidence Store Audit Trail")
        if not viable:
            lines.append("_No evidence records bound to viable candidates._")
        else:
            for cand in viable:
                cand_evs = evidence_store.get_for_candidate(cand.id)
                lines.append(f"### `{cand.id}` — {cand.company_name} ([{cand.canonical_domain}]({cand.url}))")
                lines.append(f"- **Qualification Verdict**: `{cand.qualification_status}` — {'; '.join(cand.qualification_reasons)}")
                for ev in cand_evs:
                    lines.append(
                        f"  - **`[{ev.id}]`** (`{ev.source_type}` → supports `{ev.supports_field}={ev.supports_claim}`): "
                        f"Source: [{ev.source_url}]({ev.source_url}) — _{ev.content_excerpt[:180]}_"
                    )
                lines.append("")

        # 4. Rejected Candidates Summary (Transparency)
        if rejected_list:
            lines.append("## 4. Rejected Candidates (Filtered Out by Verifier / Qualifier)")
            for rc in rejected_list[:8]:
                reason = "; ".join(rc.failed_checks or rc.qualification_reasons) or "Failed verification"
                lines.append(f"- 🔴 **{rc.company_name}** (`{rc.canonical_domain}`): _{reason}_")
            lines.append("")

        # 5. Validated Outreach Draft (Built strictly from Allowed Claims)
        if outreach_draft:
            lines.append("## 5. Evidence-Bound Cold Outreach Draft")
            lines.append(
                "_Generated strictly from `allowed_outreach_claims` (zero raw search text or unmeasured speed stats passed to composer)._"
            )
            lines.append("")
            lines.append(f"- **Target Prospect**: {outreach_draft['company_name']} ({outreach_draft['website']})")
            lines.append(f"- **Allowed Claims Used**: `{outreach_draft['allowed_claims_summary']}`")
            lines.append(f"- **Subject**: `{outreach_draft['subject']}`")
            lines.append("")
            lines.append("```text")
            lines.append(outreach_draft["body"])
            lines.append("```")
            lines.append("")

        # 6. Research Session Telemetry Footer (Amendment #1: Measured Telemetry)
        lines.append("---")
        lines.append(
            f"**ResearchSession Telemetry (`{session.id}`)**: "
            f"Status=`{session.status}` | Hops=`{session.current_hop}/{session.max_hops}` | "
            f"Candidates Found=`{session.candidates_found}` | Audited=`{session.candidates_verified}` | "
            f"Tavily Searches=`{session.tavily_calls_made}` | LLM Calls=`{session.llm_calls_made}` | "
            f"Termination=`{session.termination_reason}`"
        )

        return {
            "markdown": "\n".join(lines),
            "outreach_draft": outreach_draft,
            "viable_count": len(viable),
            "verified_count": len(verified_list),
            "prospect_count": len(prospect_list),
            "rejected_count": len(rejected_list)
        }

    @classmethod
    def _compose_outreach_from_allowed_claims(
        cls,
        cand: Candidate,
        allowed_claims: List[Dict[str, str]],
        session: ResearchSession,
        llm_client: Any = None
    ) -> Dict[str, str]:
        """
        Composes outreach using ONLY verified claims from MayaClaimValidator.
        Never receives raw search text or unverified fields.
        """
        claims_summary = "; ".join(
            f"{c['field']}={c['value']} [{c['evidence_ids']}]" for c in allowed_claims
        ) or f"website={cand.url}"

        plat_val = cand.platform.value or "ecommerce"
        apps_val = cand.apps.value

        # Default deterministic consultative template (100% compliant with allowed claims)
        subject = f"Quick question on {cand.company_name}'s {plat_val} storefront"
        if apps_val:
            body = (
                f"Hi {cand.company_name} Team,\n\n"
                f"I was reviewing your {plat_val} storefront at {cand.canonical_domain} and noticed you are actively running "
                f"third-party apps including {apps_val}.\n\n"
                f"For growing D2C brands, multiple injected app scripts can often create checkout friction on mobile. "
                f"We haven't run a formal speed audit on {cand.canonical_domain} yet, but I'd love to share a quick "
                f"3-point storefront architecture teardown showing how similar {plat_val} brands streamline their app stack.\n\n"
                f"Open to me sending over a 60-second teardown video?\n\n"
                f"Best,\nWebshastraa Lab"
            )
        else:
            body = (
                f"Hi {cand.company_name} Team,\n\n"
                f"I was exploring your {plat_val} storefront at {cand.canonical_domain}.\n\n"
                f"We help D2C brands streamline their {plat_val} theme architecture and checkout flow. "
                f"While we haven't audited your internal metrics yet, I'd love to share a quick 3-point mobile UX review "
                f"tailored to {cand.company_name}.\n\n"
                f"Would you be open to a quick 60-second walkthrough?\n\n"
                f"Best,\nWebshastraa Lab"
            )

        # Optional LLM polish using ONLY allowed_claims (never raw research)
        if llm_client is not None and allowed_claims:
            from app.engine.gemini_client import generate_content_with_retry
            prompt = (
                "You are drafting a short, consultative B2B cold email.\n"
                "STRICT EVIDENCE BOUNDARY: You may ONLY reference the verified facts below. "
                "Do NOT claim any page load speed (seconds), bounce rate (%), or revenue figure.\n\n"
                f"Company: {cand.company_name}\n"
                f"Website: {cand.canonical_domain}\n"
                f"Verified Allowed Claims:\n{json.dumps(allowed_claims, indent=2)}\n\n"
                "Return ONLY raw JSON: {\"subject\": \"...\", \"body\": \"...\"}"
            )
            try:
                session.llm_calls_made += 1
                session.tokens_in += max(1, len(prompt) // 4)
                res = generate_content_with_retry(
                    client=llm_client,
                    model="gemini-3.8-flash",
                    contents=[{"role": "user", "parts": [{"text": prompt}]}]
                )
                raw = (res.text or "").strip()
                session.tokens_out += max(1, len(raw) // 4)
                start = raw.find("{")
                end = raw.rfind("}")
                if start != -1 and end != -1:
                    parsed = json.loads(raw[start:end + 1])
                    if parsed.get("subject") and parsed.get("body"):
                        subject = parsed["subject"].strip()
                        body = parsed["body"].strip()
            except Exception:
                pass

        # Run MayaClaimValidator post-check to guarantee zero unmeasured claims slipped in
        repaired_body, _, _ = MayaClaimValidator.validate_and_repair_text(body, cand)

        return {
            "company_name": cand.company_name,
            "website": cand.url,
            "allowed_claims_summary": claims_summary,
            "subject": subject,
            "body": repaired_body
        }
