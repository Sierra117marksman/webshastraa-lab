import os
import json
import uuid
import logging
import urllib.parse
from datetime import datetime
from typing import Dict, Any, Optional
from google import genai

from app.models.employee import AIEmployeeSpec, TaskRecord
from app.models.memory import AuditLogEntry
from app.db.store import save_task, get_task, list_active_memories, save_audit_log
from app.tools.registry import (
    execute_web_search,
    execute_email_sender,
    execute_sheet_logger,
    execute_slack_notifier,
    execute_domain_verifier,
    TOOLS_METADATA
)
from app.tools.domain_verifier import verify_domain_safely
from app.engine.qualification import (
    Evidence,
    LeadField,
    VerifiedLead,
    QualificationEngine,
    OutreachClaimValidator
)
from app.engine.gemini_client import generate_content_with_retry
from app.engine.policy_engine import check_tool_permission

logger = logging.getLogger(__name__)

def get_role_mandate(department: str) -> str:
    dep = (department or '').upper()
    if 'CRM' in dep or 'SALES' in dep or 'SDR' in dep:
        return '''
CRITICAL SDR & LEAD DISCOVERY MANDATE:
1. PROACTIVE MULTI-HOP OPPORTUNITY SOURCING:
   - Your primary mission is to uncover high-value, actionable business leads, contractor/freelance opportunities, client accounts, or active hiring signals matching the prompt.
   - When calling web_search, use diverse, high-signal queries across 4 research hops: broad discovery, alternate queries, specialized directory reports, and direct company verification.
2. ZERO BRAND / URL FABRICATION (STRICT LAW):
   - Every single brand, company, or store listed MUST be a real, verified, specific entity with its actual website domain (e.g. [brand.in](https://brand.in) or [store.myshopify.com](https://store.myshopify.com)).
   - NEVER invent fictional brand names (e.g. "Arise Skincare", "Desi Loom", "Nomad Leathercraft") or link to blog articles, accelerator lists, or news posts as a company's website.
3. EPISTEMIC HONESTY & METRIC INTEGRITY (UNKNOWN MUST REMAIN UNKNOWN):
   - NEVER state unmeasured performance numbers (e.g. "3.5s load time", "4.8s mobile load", "22% bounce rate"). If unmeasured, you MUST write "NOT AUDITED (Requires speed test)".
   - NEVER invent private turnover or commercial metrics. If private brand does not publish turnover, write "UNVERIFIED (Private entity)" and use verifiable store rank/unit economics proxy.
   - Never manufacture extra leads to reach the requested quantity. If the founder asks for 10 and only 3 survive verification, RETURN 3 GENUINE LEADS. Accuracy is more important than quantity.
4. TRI-STATE QUALIFICATION SEMANTICS:
   - ✅ VERIFIED: Every user-specified hard constraint has direct supporting evidence.
   - 🟡 PROSPECT / NEEDS QUALIFICATION: Real, relevant business, but one or more hard constraints remain unverified.
   - 🔴 REJECTED: Contradicted, dead, irrelevant, or invalid.
5. OUTREACH INTEGRITY LAW:
   - Never state an unmeasured observation in outreach (e.g. replace "I noticed your site loads in 4.8s" with "I was reviewing your storefront on mobile and noticed several areas we could audit for checkout speed").
'''
    elif 'HR' in dep or 'HRM' in dep or 'TALENT' in dep:
        return '''
CRITICAL RECRUITING & TALENT EVALUATION MANDATE:
1. OBJECTIVE SCORECARD AUDITING:
   - Evaluate candidates against stated criteria, years of experience, and demonstrable portfolio projects.
   - Classify candidate profiles into: 🟢 [QUALIFIED], 🟡 [UNVERIFIED], or 🔴 [REJECTED].
2. ZERO BIAS & DETERMINISTIC VERIFICATION:
   - Verify stated timelines and tech stacks from primary sources.
   - Deliver clean candidate comparison matrices and interview preparation dossiers.
'''
    elif 'MARKETING' in dep or 'GROWTH' in dep or 'CONTENT' in dep:
        return '''
CRITICAL GROWTH & CONTENT INTELLIGENCE MANDATE:
1. MARKET SIGNAL EXTRACTION:
   - Identify trending developments, competitive announcements, and technological breakthroughs.
2. COMPELLING THOUGHT LEADERSHIP:
   - Produce ready-to-publish hooks, technical breakdowns, and executive commentary tailored for LinkedIn/Twitter.
   - Maintain high clarity, strong narrative tension, and immediate founder value.
'''
    else:  # Operations / Finance / Accounting (David Kim)
        return '''
CRITICAL RECONCILIATION & AUDIT MANDATE:
1. IMMUTABLE TASK CONSTRAINTS:
   - Preserve contract caps, agreed billing rates, and line-item thresholds strictly.
2. MATHEMATICAL RECALCULATION & TRI-STATE AUDIT:
   - Recalculate all billing math deterministically. Classify entries into: 🟢 [PASS], 🔴 [HOLD - Discrepancy], 🟡 [UNVERIFIED].
3. ACTION AUTHORITY DEMARCATION:
   - Operate as an audit analyst. Phrase verdicts strictly as "RECOMMEND PASS" or "RECOMMEND HOLD".
'''


def get_followup_instructions(department: str) -> str:
    dep = (department or '').upper()
    if 'CRM' in dep or 'SALES' in dep or 'SDR' in dep:
        return '''
Synthesize your findings into a comprehensive, high-impact Lead & Opportunity Dossier:
1. EXECUTIVE MARKET SUMMARY:
   - High-level briefing on the landscape discovered.
   - Explicitly separate Verified Data from Unverified Proxies (e.g. private turnover is not public; state the proxy unit economics: ₹83k–₹4L/mo at ₹1k AOV).
2. STRUCTURED PROSPECT / OPPORTUNITIES TABLE:
   - For Brand / Store Prospecting:
     | # | Brand / Store | Direct Website | Platform (Verified/Unverified) | Detected Apps | Revenue Status | Website & UX Status | Lead Status (✅ VERIFIED / 🟡 PROSPECT / 🔴 REJECTED) | Source Citation | Founder Pitch Angle |
   - For Freelance / Contractor Gigs:
     | # | Company / Client | Role / Project Type | Engagement Model | Location | Compensation / Budget | Lead Status | Direct Link |
   (Ensure EVERY link is a live clickable markdown link directly to that specific store/job, NOT a general news blog)
   (Hard Rule: Unknown fields must be labeled UNVERIFIED or NOT AUDITED. If only 3 leads survive verification, list 3. Never invent filler rows.)
3. DEEP-DIVE PROSPECT TEARDOWNS:
   For the strongest leads discovered, provide:
   - Storefront & catalog context
   - Visible technology & app stack (e.g. Nudgify, Wati, Fera, Easysize, Smile.io)
   - Specific conversion leaks or mobile UX friction points (clearly labeled as observed hypotheses, not unmeasured load speed facts)
   - Project scope & redesign / automation opportunity
4. FOUNDER POSITIONING & COLD OUTREACH PLAYBOOK:
   - The pitch strategy (e.g. pitch a 60-second mobile conversion leak audit; never claim unmeasured speed numbers)
   - 3-sentence value proposition
   - Complete, ready-to-dispatch personalized cold email draft (To, Subject, Body)
'''
    elif 'HR' in dep or 'HRM' in dep or 'TALENT' in dep:
        return '''
Synthesize your findings into a Talent Screening & Candidate Audit Dossier:
1. ROLE SCORECARD & CRITERIA RECAP
2. CANDIDATE COMPARISON MATRIX:
   | Status | Candidate | Key Skills | Verified Experience | Scorecard Match | Recommendation |
3. CANDIDATE PROFILES & EVIDENCE AUDIT
4. NEXT ACTIONS & INTERVIEW QUESTION BANK
'''
    elif 'MARKETING' in dep or 'GROWTH' in dep or 'CONTENT' in dep:
        return '''
Synthesize your findings into a Growth & Content Intelligence Brief:
1. MARKET BREAKTHROUGH SUMMARY
2. READY-TO-POST CONTENT ARTIFACTS:
   - 3 distinct storytelling angles (e.g. Case Study, Contrarian Take, Architecture Breakdown)
3. STRATEGIC POSITIONING TAKEAWAY FOR THE FOUNDER
'''
    else:  # Operations / David Kim
        return '''
Synthesize your final deliverable adhering strictly to Defensible Audit Standards:
1. TASK CONSTRAINTS & AUDIT SCOPE
2. STRUCTURED VERIFICATION TABLE:
   | Status | Entity / Vendor | Billed Amount | Calculated / Contract Math | Contract Cap | Net Variance | Recommendation |
3. DETERMINISTIC AUDIT FINDINGS & DISCREPANCIES
4. VERDICT (Phrase strictly as "RECOMMEND PASS" or "RECOMMEND HOLD")
'''


RUNNER_PROMPT_TEMPLATE = '''
You are {name}, working as an autonomous {role} in the {department} department.
Current Calendar Date: {current_date}
Your Core Mission: {objective}
Your Behavioral Persona: {persona}

Your Standard Operating Procedures (SOPs):
{sops_formatted}

Available Tools:
{tools_formatted}

{memories_section}
Current Task:
{task_prompt}

{role_mandate}

CRITICAL TOOL INVOCATION RULE:
- If the task requires researching live web facts, dates, companies, jobs, or market events, you MUST set "action_type": "call_tool", "tool_name": "web_search", and provide "tool_params": {{"query": "<specific search keywords>"}}.
- NEVER set "action_type": "finish" with a null or empty "final_response".
- If finishing, you MUST provide the complete, comprehensive markdown deliverable inside "final_response".

Analyze the task and determine the best action.
Respond in valid JSON with:
- "thought": (Your internal reasoning about what to do next based on your role and SOPs)
- "action_type": ("call_tool" or "finish")
- "tool_name": (Name of tool to call, or null if finishing)
- "tool_params": (Dictionary of tool parameters, or null)
- "final_response": (If finishing, provide your complete detailed briefing / deliverable for the founder)

Output ONLY raw parseable JSON. No markdown code blocks.
'''

def parse_json_safely(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    clean = text.strip()
    if clean.startswith('```json'):
        clean = clean[7:]
    if clean.startswith('```'):
        clean = clean[3:]
    if clean.endswith('```'):
        clean = clean[:-3]
    clean = clean.strip()
    try:
        return json.loads(clean, strict=False)
    except Exception:
        pass

    try:
        start = clean.find('{')
        end = clean.rfind('}')
        if start != -1 and end != -1:
            return json.loads(clean[start:end+1], strict=False)
    except Exception:
        pass
    return {}

def execute_tool_call(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    normalized = tool_name.lower().replace(' ', '_').strip() if tool_name else ''
    if 'search' in normalized or normalized == 'web_search':
        return execute_web_search(params.get('query', ''))
    elif 'email' in normalized or normalized == 'email_sender':
        return execute_email_sender(params.get('to', ''), params.get('subject', ''), params.get('body', ''))
    elif 'sheet' in normalized or normalized == 'sheet_logger':
        return execute_sheet_logger(params.get('table', 'general_records'), params.get('record', {}))
    elif 'slack' in normalized or normalized == 'slack_notifier':
        return execute_slack_notifier(params.get('channel', '#general'), params.get('message', ''))
    elif 'domain' in normalized or normalized == 'domain_verifier':
        return execute_domain_verifier(params.get('url', ''))
    return {'error': f'Tool {tool_name} not recognized.'}

MAX_CIRCUIT_BREAKER_STEPS = 3

def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def calculate_task_cost(tokens_in: int, tokens_out: int, tools_called: list) -> float:
    # Gemini 3.6 Flash pricing: $0.075 per 1M input tokens, $0.30 per 1M output tokens
    llm_cost = (tokens_in * 0.000000075) + (tokens_out * 0.0000003)
    # Tavily live web search API: ~$0.005 per query
    tavily_cost = sum(0.005 for t in tools_called if t == 'web_search')
    return round(llm_cost + tavily_cost, 5)

def run_employee_task(employee: AIEmployeeSpec, task_prompt: str) -> TaskRecord:
    task_id = f'task_{str(uuid.uuid4())[:8]}'
    record = TaskRecord(
        id=task_id,
        employee_id=employee.id,
        employee_name=employee.name,
        task_prompt=task_prompt,
        status='running',
        steps=[],
        tokens_used=0,
        cost_usd=0.0004,
        time_saved_mins=20
    )
    save_task(record)

    api_key = os.getenv('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)

    sops_formatted = '\n'.join(f'- {s}' for s in employee.sops)
    tools_formatted = json.dumps([t for t in TOOLS_METADATA if t['id'] in employee.tools], indent=2)

    # ── Memory injection ──────────────────────────────────────────────────────
    active_memories = list_active_memories(employee.id)
    memory_ids_used = [m.id for m in active_memories]

    if active_memories:
        mem_lines = []
        for m in active_memories:
            scope_tag = f"[{m.scope}] " if m.scope != "global" else ""
            mem_lines.append(f"- {scope_tag}{m.distilled_rule}  (priority {m.priority}, source: {m.source})")
        memories_section = (
            "MANDATORY LESSONS LEARNED — CHECK BEFORE EVERY ACTION:\n"
            "The following rules were extracted from past mistakes and founder feedback.\n"
            "Before taking any action, verify it does not violate any rule below.\n\n"
            + "\n".join(mem_lines)
            + "\n"
        )
    else:
        memories_section = ""

    current_date = datetime.now().strftime('%B %d, %Y')
    prompt = RUNNER_PROMPT_TEMPLATE.format(
        name=employee.name,
        current_date=current_date,
        role=employee.role,
        department=employee.department,
        objective=employee.objective,
        persona=employee.persona,
        sops_formatted=sops_formatted,
        tools_formatted=tools_formatted,
        memories_section=memories_section,
        task_prompt=task_prompt,
        role_mandate=get_role_mandate(employee.department)
    )

    # ── Audit: dispatch event ─────────────────────────────────────────────────
    _log_audit(
        employee_id=employee.id,
        task_id=task_id,
        event_type="dispatch",
        memories_used=memory_ids_used,
        output_summary=f"Task dispatched: {task_prompt[:120]}",
    )

    tools_called = []
    tokens_in = estimate_tokens(prompt)
    tokens_out = 0

    try:
        response = generate_content_with_retry(
            client=client,
            model='gemini-3.8-flash',
            contents=[{'role': 'user', 'parts': [{'text': prompt}]}]
        )

        raw_text = response.text.strip()
        tokens_out += estimate_tokens(raw_text)
        plan = parse_json_safely(raw_text)

        thought = plan.get('thought', 'Analyzing request...')
        action_type = plan.get('action_type', 'finish')
        tool_name = plan.get('tool_name')
        tool_params = plan.get('tool_params') or {}

        # Self-healing: if model intended to search or returned finish with empty response, auto-invoke search
        has_search_tool = any('search' in t.lower() for t in employee.tools)
        if has_search_tool:
            if action_type == 'finish' and not plan.get('final_response'):
                action_type = 'call_tool'
                tool_name = 'web_search'
                tool_params = {'query': task_prompt[:120]}
            elif action_type == 'call_tool' and not tool_name:
                tool_name = 'web_search'
                if not tool_params.get('query'):
                    tool_params = {'query': task_prompt[:120]}

        # ── Policy Engine check (replaces legacy requires_approval_for list) ──
        if action_type == 'call_tool' and tool_name:
            policy = check_tool_permission(employee.id, tool_name, tool_params, task_id)
            if not policy.allowed:
                record.status = 'failed'
                record.final_output = f'Policy block: {policy.reason}'
                record.completed_at = datetime.utcnow().isoformat()
                save_task(record)
                return record
            if policy.requires_approval:
                record.status = 'waiting_approval'
                record.pending_action = {
                    'tool_name': tool_name,
                    'tool_params': tool_params,
                    'explanation': thought
                }
                record.steps.append({
                    'step_number': 1,
                    'thought': thought,
                    'tool_called': tool_name,
                    'tool_input': tool_params,
                    'tool_output': 'PAUSED: Awaiting Founder Approval'
                })
                record.tokens_used = tokens_in + tokens_out
                record.cost_usd = calculate_task_cost(tokens_in, tokens_out, tools_called)
                save_task(record)
                return record

        # Execute tool if needed
        tool_output = None
        if action_type == 'call_tool' and tool_name:
            tools_called.append(tool_name)
            tool_output = execute_tool_call(tool_name, tool_params)

            # Multi-Hop Research Recovery Guard (Solves Failure 1: Premature Stopping)
            if tool_name == 'web_search' and isinstance(tool_output, dict):
                results = tool_output.get('results', [])
                unique_domains = {urllib.parse.urlparse(r.get('url', '')).netloc for r in results if r.get('url')}
                needs_recovery = len(results) < 3 or len(unique_domains) < 2

                if needs_recovery:
                    logger.info("[Research Recovery] Hop 1 results sparse or low diversity. Firing Hop 2 & Hop 3 recovery queries...")
                    orig_q = tool_params.get('query', task_prompt)
                    # Hop 2: Alternate query formulation
                    hop2_res = execute_web_search(f"{orig_q} directory listings platform")
                    # Hop 3: Specialized directory footprint
                    hop3_res = execute_web_search(f"site:storeleads.app {orig_q}")

                    seen_urls = {r.get('url') for r in results if r.get('url')}
                    combined_res = list(results)
                    for r in hop2_res.get('results', []) + hop3_res.get('results', []):
                        u = r.get('url')
                        if u and u not in seen_urls:
                            seen_urls.add(u)
                            combined_res.append(r)
                    tool_output['results'] = combined_res[:20]
                    tool_output['recovery_executed'] = True

            record.steps.append({
                'step_number': 1,
                'thought': thought,
                'tool_called': tool_name,
                'tool_input': tool_params,
                'tool_output': tool_output
            })

            # Secondary pass to synthesize final output adhering to role standards
            followup_instructions = get_followup_instructions(employee.department)
            followup_prompt = f'''
            Current Calendar Date: {current_date}

            Raw Tool Results / Live Web Intel:
            {json.dumps(tool_output, indent=2)}

            {followup_instructions}

            Output ONLY valid raw JSON with:
            - "thought": (Your internal analysis of the findings)
            - "action_type": ("finish" or "call_tool" if another targeted search is essential)
            - "tool_name": (Tool name if calling again, or null)
            - "tool_params": (Dictionary of params, or null)
            - "final_response": (If finishing, provide your complete, detailed markdown deliverable for the founder)
            '''
            tokens_in += estimate_tokens(followup_prompt)
            final_res = generate_content_with_retry(
                client=client,
                model='gemini-3.8-flash',
                contents=[
                    {'role': 'user', 'parts': [{'text': prompt}]},
                    {'role': 'model', 'parts': [{'text': raw_text}]},
                    {'role': 'user', 'parts': [{'text': followup_prompt}]}
                ]
            )

            tokens_out += estimate_tokens(final_res.text)
            clean_text = final_res.text.strip()
            step2_plan = parse_json_safely(clean_text)
            step2_thought = step2_plan.get('thought', 'Synthesizing output...')
            step2_action = step2_plan.get('action_type', 'finish')
            step2_tool = step2_plan.get('tool_name')
            step2_params = step2_plan.get('tool_params') or {}

            if step2_action == 'call_tool' and step2_tool:
                step2_policy = check_tool_permission(employee.id, step2_tool, step2_params, task_id)
                if not step2_policy.allowed:
                    record.status = 'failed'
                    record.final_output = f'Policy block at step 2: {step2_policy.reason}'
                    record.completed_at = datetime.utcnow().isoformat()
                    save_task(record)
                    return record
                if step2_policy.requires_approval:
                    record.status = 'waiting_approval'
                    record.pending_action = {
                        'tool_name': step2_tool,
                        'tool_params': step2_params,
                        'explanation': step2_thought
                    }
                    record.steps.append({
                        'step_number': 2,
                        'thought': step2_thought,
                        'tool_called': step2_tool,
                        'tool_input': step2_params,
                        'tool_output': 'PAUSED: Awaiting Founder Approval'
                    })
                    record.tokens_used = tokens_in + tokens_out
                    record.cost_usd = calculate_task_cost(tokens_in, tokens_out, tools_called)
                    save_task(record)
                    return record

                # Tool is permitted: execute Step 2 tool
                tools_called.append(step2_tool)
                step2_out = execute_tool_call(step2_tool, step2_params)
                record.steps.append({
                    'step_number': 2,
                    'thought': step2_thought,
                    'tool_called': step2_tool,
                    'tool_input': step2_params,
                    'tool_output': step2_out
                })

                # Step 3: Multi-hop final synthesis from all collected evidence
                final_instructions = get_followup_instructions(employee.department)
                final_prompt = f'''
                Current Calendar Date: {current_date}

                All Collected Evidence from Multi-Hop Research:
                Round 1 Evidence:
                {json.dumps(tool_output, indent=2)}

                Round 2 Evidence:
                {json.dumps(step2_out, indent=2)}

                {final_instructions}

                Output ONLY valid raw JSON with:
                - "thought": (Your final synthesis thoughts)
                - "action_type": "finish"
                - "final_response": (Your complete, exhaustive markdown deliverable for the founder)
                '''
                tokens_in += estimate_tokens(final_prompt)
                try:
                    step3_res = generate_content_with_retry(
                        client=client,
                        model='gemini-3.8-flash',
                        contents=[
                            {'role': 'user', 'parts': [{'text': prompt}]},
                            {'role': 'model', 'parts': [{'text': raw_text}]},
                            {'role': 'user', 'parts': [{'text': followup_prompt}]},
                            {'role': 'model', 'parts': [{'text': clean_text}]},
                            {'role': 'user', 'parts': [{'text': final_prompt}]}
                        ]
                    )
                    tokens_out += estimate_tokens(step3_res.text)
                    step3_text = step3_res.text.strip()
                    step3_plan = parse_json_safely(step3_text)
                    record.final_output = step3_plan.get('final_response') or step3_res.text
                except Exception as e:
                    logger.error(f"[Runner Step 3 Error] {e}", exc_info=True)
                    record.final_output = step2_plan.get('final_response') or final_res.text
            else:
                record.final_output = step2_plan.get('final_response') or clean_text
        else:
            record.steps.append({
                'step_number': 1,
                'thought': thought,
                'tool_called': None,
                'tool_input': None,
                'tool_output': 'Direct synthesis completed'
            })
            record.final_output = plan.get('final_response') or raw_text or 'Task concluded successfully.'

        # Unpack JSON if final_output is still a JSON string
        if record.final_output and isinstance(record.final_output, str):
            parsed = parse_json_safely(record.final_output)
            if isinstance(parsed, dict) and parsed:
                if parsed.get('final_response'):
                    record.final_output = parsed['final_response']
                elif parsed.get('thought') and parsed.get('action_type') != 'call_tool':
                    record.final_output = parsed['thought']

        # Deterministic Outreach & Metric Validation Pass (Failure 2 fix)
        if record.final_output and isinstance(record.final_output, str):
            unverified_ctx = VerifiedLead(
                company_name="Audit Candidate",
                website="https://candidate-audit.com",
                platform=LeadField(status="UNVERIFIED"),
                apps=LeadField(status="UNVERIFIED"),
                revenue=LeadField(status="UNVERIFIED"),
                website_observation=LeadField(status="NOT_AUDITED"),
                contact=LeadField(status="UNVERIFIED")
            )
            sanitized, was_mod, violations = OutreachClaimValidator.validate_and_sanitize_outreach(
                record.final_output,
                unverified_ctx
            )
            if was_mod:
                record.final_output = sanitized
                logger.info(f"[Outreach Validator] Sanitized {len(violations)} unverified performance/bounce claims in deliverable.")

        record.status = 'completed'
        record.tokens_used = tokens_in + tokens_out
        record.cost_usd = calculate_task_cost(tokens_in, tokens_out, tools_called)
        record.completed_at = datetime.utcnow().isoformat()
        save_task(record)
        return record

    except Exception as e:
        record.status = 'failed'
        record.final_output = f'Execution error: {str(e)}'
        record.completed_at = datetime.utcnow().isoformat()
        save_task(record)
        return record


def _log_audit(
    employee_id: str,
    task_id: str,
    event_type: str,
    memories_used: list = None,
    tools_called: list = None,
    decision: str = None,
    output_summary: str = "",
    founder_feedback: str = None,
    cost_usd: float = 0.0,
    tokens_used: int = 0,
):
    """Write an audit log entry. Silently swallows errors so it never crashes the pipeline."""
    try:
        entry = AuditLogEntry(
            id=f"audit_{uuid.uuid4().hex[:12]}",
            employee_id=employee_id,
            task_id=task_id,
            event_type=event_type,  # type: ignore[arg-type]
            memories_used=memories_used or [],
            tools_called=tools_called or [],
            decision=decision,
            output_summary=output_summary[:500],
            founder_feedback=founder_feedback,
            cost_usd=cost_usd,
            tokens_used=tokens_used,
            timestamp=datetime.utcnow().isoformat(),
        )
        save_audit_log(entry)
    except Exception as exc:
        logger.warning(f"[Audit log write failed] {exc}")


def resume_approved_task(task_id: str, approved: bool, founder_feedback: Optional[str] = None) -> TaskRecord:
    record = get_task(task_id)
    if not record or record.status != 'waiting_approval':
        return record

    if not approved:
        record.status = 'rejected'
        record.final_output = f'Action rejected by founder. Feedback: {founder_feedback or "No feedback given."}'
        record.completed_at = datetime.utcnow().isoformat()
        save_task(record)

        # ── Reflection trigger ────────────────────────────────────────────────
        # Generate a proposed memory from the rejection feedback (async-safe, best-effort)
        if founder_feedback and founder_feedback.strip():
            try:
                from app.engine.reflector import generate_proposed_memory
                from app.db.store import save_memory, get_employee
                emp = get_employee(record.employee_id)
                if emp:
                    proposed = generate_proposed_memory(
                        employee_id=emp.id,
                        employee_name=emp.name,
                        employee_role=emp.role,
                        task_id=task_id,
                        task_prompt=record.task_prompt,
                        what_happened=str(record.pending_action or "Pending tool action"),
                        feedback=founder_feedback,
                        trigger_event="rejection",
                    )
                    if proposed:
                        save_memory(proposed)
                        _log_audit(
                            employee_id=record.employee_id,
                            task_id=task_id,
                            event_type="reflection_proposed",
                            decision=f"Proposed memory: {proposed.id}",
                            output_summary=proposed.distilled_rule[:200],
                            founder_feedback=founder_feedback,
                        )
            except Exception as exc:
                logger.warning(f"[Reflection failed] {exc}")

        _log_audit(
            employee_id=record.employee_id,
            task_id=task_id,
            event_type="approval_rejected",
            decision="Rejected",
            founder_feedback=founder_feedback,
            output_summary=record.final_output[:200],
        )
        return record

    # Approved: policy check the pending tool before executing
    pending = record.pending_action or {}
    tool_name = pending.get('tool_name')
    tool_params = pending.get('tool_params') or {}

    policy = check_tool_permission(record.employee_id, tool_name, tool_params, task_id)
    if not policy.allowed:
        record.status = 'failed'
        record.final_output = f'Post-approval policy block: {policy.reason}'
        record.completed_at = datetime.utcnow().isoformat()
        save_task(record)
        return record

    result = execute_tool_call(tool_name, tool_params)
    record.steps.append({
        'step_number': len(record.steps) + 1,
        'thought': f'Approved by Founder. Executing {tool_name}.',
        'tool_called': tool_name,
        'tool_input': tool_params,
        'tool_output': result
    })

    record.status = 'completed'
    record.final_output = f'Successfully executed {tool_name} after founder sign-off: {json.dumps(result)}'
    record.completed_at = datetime.utcnow().isoformat()
    record.pending_action = None
    save_task(record)

    _log_audit(
        employee_id=record.employee_id,
        task_id=task_id,
        event_type="approval_granted",
        tools_called=[tool_name],
        decision="Approved and executed",
        founder_feedback=founder_feedback,
        output_summary=record.final_output[:200],
    )
    return record

