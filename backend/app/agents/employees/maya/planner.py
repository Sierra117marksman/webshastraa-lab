import re
import uuid
from typing import List
from app.agents.schemas.session import ResearchSession


class MayaPlanner:
    """
    Translates a raw user task prompt into a structured ResearchSession
    (hard_constraints, soft_constraints, target_leads) and generates
    distinct search queries for each hop (Hops 1 through 4).
    """

    @staticmethod
    def create_session(task_id: str, task_prompt: str) -> ResearchSession:
        lower = task_prompt.lower()

        # 1. Extract target lead count (default 10, cap at 20)
        count_match = re.search(r'\b(\d{1,2})\s+(?:business|businesses|brand|brands|store|stores|lead|leads|prospect|prospects|compan)', lower)
        target_leads = int(count_match.group(1)) if count_match else 10
        target_leads = max(1, min(target_leads, 20))

        # 2. Extract hard vs soft constraints
        hard_constraints = {}
        soft_constraints = {}

        # Platform detection
        if "shopify" in lower:
            hard_constraints["platform"] = "Shopify"
        elif "woocommerce" in lower or "wordpress" in lower:
            hard_constraints["platform"] = "WooCommerce"

        # Business model detection
        if "d2c" in lower or "direct to consumer" in lower or "brand" in lower or "store" in lower:
            hard_constraints["d2c_status"] = "D2C / Ecommerce Store"

        # App usage detection
        if "app" in lower or "wati" in lower or "loox" in lower or "nudgify" in lower or "judge.me" in lower:
            hard_constraints["apps"] = "Installed Ecommerce Apps"

        # Geography
        if "india" in lower or "indian" in lower or "lakh" in lower or "₹" in lower:
            hard_constraints["geography"] = "India"

        # Revenue / Turnover (Private commercial metric — tracked so Qualifier knows if it's unverified)
        if any(k in lower for k in ["turnover", "revenue", "lakh", "crore", "arr", "mrr"]):
            hard_constraints["revenue_requested"] = True
            soft_constraints["revenue_target"] = "₹10L–₹50L annual turnover (Private entity metric)"

        # Website quality / UX
        if any(k in lower for k in ["old", "crappy", "slow", "website", "redesign", "speed", "ux"]):
            soft_constraints["website_observation"] = "Storefront UX & app script footprint"

        # Outreach requested?
        soft_constraints["draft_outreach"] = any(
            k in lower for k in ["email", "outreach", "pitch", "contact", "send"]
        )

        # Niche keywords
        niche_words = []
        for kw in ["skincare", "beauty", "fashion", "apparel", "jewelry", "jewellery", "footwear", "ayurveda", "wellness", "food", "home"]:
            if kw in lower:
                niche_words.append(kw)
        soft_constraints["niche"] = ", ".join(niche_words) if niche_words else "D2C Ecommerce"

        return ResearchSession(
            id=f"sess_{uuid.uuid4().hex[:8]}",
            task_id=task_id,
            raw_prompt=task_prompt,
            hard_constraints=hard_constraints,
            soft_constraints=soft_constraints,
            target_leads=target_leads,
            current_hop=0,
            max_hops=4,
            max_candidates=50,
            max_verification_requests=50,
            status="discovering"
        )

    @staticmethod
    def generate_hop_queries(session: ResearchSession, hop: int) -> List[str]:
        """
        Generates distinct, non-overlapping search queries for Hop 1, 2, 3, and 4.
        Never repeats a query already in session.search_queries_used.
        """
        platform = session.hard_constraints.get("platform", "Shopify")
        niche = session.soft_constraints.get("niche", "D2C")
        geo = session.hard_constraints.get("geography", "India")
        raw = session.raw_prompt[:100]

        if hop == 1:
            # Hop 1: Direct store footprint & primary niche discovery
            candidates = [
                f'site:storeleads.app "country/IN" "{platform}" "Wati" OR "Nudgify" OR "Fera"',
                f'{geo} {niche} {platform} D2C brands stores using apps'
            ]
        elif hop == 2:
            # Hop 2: App-specific technology footprints
            candidates = [
                f'site:storeleads.app "country/IN" "Judge.me" OR "Loox" OR "Smile.io" OR "Easysize"',
                f'site:myshopify.com "{geo}" D2C skincare fashion store'
            ]
        elif hop == 3:
            # Hop 3: Regional store directory reports
            candidates = [
                f'site:storeleads.app "reports/shopify/IN" "Domain" "Rank"',
                f'"{platform}" D2C brands in {geo} official store ".in" OR ".com" shopping'
            ]
        else:
            # Hop 4: Broad fallback / alternative terminology
            candidates = [
                f'{raw} official website store',
                f'emerging D2C ecommerce brands {geo} {platform} store directory'
            ]

        fresh = [q for q in candidates if q not in session.search_queries_used]
        session.search_queries_used.extend(fresh)
        return fresh
