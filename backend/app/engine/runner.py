import os
import json
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from google import genai

from app.models.employee import AIEmployeeSpec, TaskRecord
from app.db.store import save_task, get_task
from app.tools.registry import (
    execute_web_search,
    execute_email_sender,
    execute_sheet_logger,
    execute_slack_notifier,
    TOOLS_METADATA
)
from app.engine.gemini_client import generate_content_with_retry

RUNNER_PROMPT_TEMPLATE = '''
You are {name}, working as an autonomous {role} in the {department} department.
Current Calendar Date: {current_date}
Your Core Mission: {objective}
Your Behavioral Persona: {persona}

Your Standard Operating Procedures (SOPs):
{sops_formatted}

Available Tools:
{tools_formatted}

Current Task:
{task_prompt}

CRITICAL RESEARCH & VERIFICATION MANDATE:
1. IMMUTABLE TASK CONSTRAINT NORMALIZATION:
   - Preserve the user's constraints exactly. Do NOT widen, reinterpret, substitute, or drift from the requested date range, entity category, funding round, funding threshold, quantity, or ranking instruction.
   - At the beginning of your deliverable, output a normalized TASK CONSTRAINTS block:
     - Entity Category: (e.g. AI-agent startups only)
     - Funding Round: (e.g. Series B only, or as requested)
     - Funding Amount Threshold: (e.g. > $50M USD)
     - Announcement Window: (Exact start date through exact end date inclusive; never widen)
     - Result Requirement: (e.g. ALL qualifying companies, or Top N if requested)
     - Exclusions: (e.g. Acquisitions, unclosed negotiations/rumors, hardware ASICs, older rounds)
     - Required Fields: (Company, Amount, Lead Investor, Exact Announcement Date, Primary Source URL)
   - Nothing downstream is allowed to modify or widen these constraints!

2. EPISTEMIC TRI-STATE VERIFICATION CLASSIFICATION:
   Every discovered candidate entity MUST be explicitly classified into one of three definitive states:
   - 🟢 [QUALIFIED] — Evidence affirmatively satisfies 100% of the immutable constraints with verified primary-source reporting.
   - 🔴 [REJECTED - <Exact Criterion Failed>] — Candidate was discovered or audited but demonstrably fails at least one constraint. Specify the EXACT criterion that failed (e.g. '[REJECTED - Round Mismatch: Series C instead of Series B]', '[REJECTED - Date Out of Window: Announced August 4, 2026, outside Sep 1-Sep 8 window]', '[REJECTED - Excluded: Acquisition by Stripe, not equity funding]').
   - 🟡 [UNVERIFIED - <Reason Incomplete>] — Candidate was surfaced, but retrieved evidence is insufficient to determine full compliance (e.g. '[UNVERIFIED - Incomplete Reporting: Series B announced in Sep 2026, but disclosed amount or lead investor not confirmed in primary text]').

3. EPISTEMIC HUMILITY ON ZERO RESULTS:
   - Distinguish "My retrieved evidence did not establish any qualifying companies" from "There were no such companies in existence".
   - If 0 qualify, explicitly state: "In the retrieved live web evidence, 0 candidates strictly met all immutable constraints. Below is the audited breakdown of candidates discovered, rejected, and unverified."

4. ZERO CITATION LAUNDERING:
   - Never assert unverified quantitative metrics (e.g. '3.4x faster', '65% cycle time reduction') without a named primary source.

5. ENTITY PROVENANCE & PRIMARY SOURCES:
   - When citing funding rounds, include markdown links to the primary press release or source URLs retrieved in live search.

CRITICAL TOOL INVOCATION RULE:
- If the task requires researching live web facts, dates, companies, or events, you MUST set "action_type": "call_tool", "tool_name": "web_search", and provide "tool_params": {{"query": "<specific search keywords>"}}.
- NEVER set "action_type": "finish" with a null or empty "final_response".
- If finishing, you MUST provide the complete, comprehensive markdown deliverable inside "final_response".

Analyze the task and determine the best action.
Respond in valid JSON with:
- "thought": (Your internal reasoning about what to do next based on your SOPs and verification standards)
- "action_type": ("call_tool" or "finish")
- "tool_name": (Name of tool to call, or null if finishing)
- "tool_params": (Dictionary of tool parameters, or null)
- "final_response": (If finishing, provide your complete detailed briefing / deliverables for the founder adhering to verification standards)

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
        task_prompt=task_prompt
    )

    tools_called = []
    tokens_in = estimate_tokens(prompt)
    tokens_out = 0

    try:
        response = generate_content_with_retry(
            client=client,
            model='gemini-3.5-flash',
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

        # Check if action requires human-in-the-loop approval
        if action_type == 'call_tool' and tool_name in employee.requires_approval_for:
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
            record.steps.append({
                'step_number': 1,
                'thought': thought,
                'tool_called': tool_name,
                'tool_input': tool_params,
                'tool_output': tool_output
            })

            # Secondary pass to synthesize final output adhering to verification standards
            followup_prompt = f'''
            Current Calendar Date: {current_date}

            Raw Tool Results / Live Web Intel:
            {json.dumps(tool_output, indent=2)}

            Synthesize your final deliverable adhering strictly to Defensible Research & Audit Standards:
            1. IMMUTABLE TASK CONSTRAINTS BLOCK:
               Output an explicit, immutable constraints block at the very beginning of your deliverable:
               - Entity Category: (e.g. AI-agent startups only)
               - Funding Round: (e.g. Series B only, or as requested)
               - Funding Amount Threshold: (e.g. > $50M USD)
               - Announcement Window: (Exact start date through exact end date inclusive; NEVER widen or reinterpret to "Top 2" or different dates)
               - Result Scope: (e.g. ALL qualifying companies, NOT a top-N subset)
               - Exclusions: (Acquisitions, rumors, hardware ASICs, non-agent tech)
               - Required Fields: (Company, Round, Disclosed Amount, Lead Investor, Announcement Date, Primary Source URL)

            2. STRUCTURED VERIFICATION TABLE:
               | Status | Company | Round | Disclosed USD Amount | Lead Investor | Announcement Date | Primary Source Link |
               (List ONLY [QUALIFIED] candidates here. If 0 candidates qualify in retrieved evidence, display "— None Qualified in Retrieved Evidence —")

            3. EPISTEMIC TRI-STATE VERIFICATION & AUDIT LOG:
               Evaluate and classify EVERY discovered candidate entity into:
               - 🟢 [QUALIFIED] — Affirmatively satisfies 100% of immutable constraints with primary-source evidence.
               - 🔴 [REJECTED - <Exact Criterion Failed>] — Demonstrably fails at least one constraint (state exact reason: e.g. "Round Mismatch: Series C instead of Series B", "Date Out of Window: Announced August 4, 2026", "Excluded: Acquisition by Stripe").
               - 🟡 [UNVERIFIED - <Reason Incomplete>] — Surfaced in reporting, but retrieved evidence is insufficient/ambiguous to verify all mandatory fields.

            4. EPISTEMIC HUMILITY ON ZERO RESULTS:
               - Distinguish "My retrieved evidence did not establish any qualifying companies" from an absolute claim that none exist.
               - State clearly: "In the retrieved live web evidence across search passes, 0 candidates strictly verified as [QUALIFIED] across all constraints. Below is the audited breakdown of candidates discovered, rejected, and unverified."

            5. ZERO CITATION LAUNDERING:
               - No fabricated metrics or unverified multipliers. All links must be real markdown links to retrieved URLs.

            Output ONLY valid raw JSON with:
            - "thought": (Your internal analysis of the findings and verification audit)
            - "action_type": "finish"
            - "final_response": (Your complete, exhaustive markdown deliverable for the founder adhering to all verification, provenance, and audit standards)
            '''
            tokens_in += estimate_tokens(followup_prompt)
            final_res = generate_content_with_retry(
                client=client,
                model='gemini-3.5-flash',
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

            if step2_action == 'call_tool' and step2_tool in employee.requires_approval_for:
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
            elif step2_action == 'call_tool' and step2_tool:
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
                final_prompt = f'''
                Current Calendar Date: {current_date}

                All Collected Evidence from Multi-Hop Research:
                Round 1 Evidence:
                {json.dumps(tool_output, indent=2)}

                Round 2 Evidence:
                {json.dumps(step2_out, indent=2)}

                Synthesize your FINAL complete deliverable adhering strictly to Defensible Research & Audit Standards:
                1. IMMUTABLE TASK CONSTRAINTS BLOCK:
                   Output an explicit, immutable constraints block at the very beginning of your deliverable:
                   - Entity Category: (e.g. AI-agent startups only)
                   - Funding Round: (e.g. Series B only, or as requested)
                   - Funding Amount Threshold: (e.g. > $50M USD)
                   - Announcement Window: (Exact start date through exact end date inclusive; NEVER widen or reinterpret)
                   - Result Scope: (e.g. ALL qualifying companies, NOT a top-N subset)
                   - Exclusions: (Acquisitions, rumors, hardware ASICs, non-agent tech)
                   - Required Fields: (Company, Round, Disclosed Amount, Lead Investor, Announcement Date, Primary Source URL)

                2. STRUCTURED VERIFICATION TABLE:
                   | Status | Company | Round | Disclosed USD Amount | Lead Investor | Announcement Date | Primary Source Link |
                   (List ONLY [QUALIFIED] candidates here. If 0 qualify in retrieved evidence, display "— None Qualified in Retrieved Evidence —")

                3. EPISTEMIC TRI-STATE VERIFICATION & AUDIT LOG:
                   Evaluate and classify EVERY discovered candidate entity into:
                   - 🟢 [QUALIFIED] — Affirmatively satisfies 100% of immutable constraints with primary-source evidence.
                   - 🔴 [REJECTED - <Exact Criterion Failed>] — Demonstrably fails at least one constraint (state exact reason: e.g. "Round Mismatch: Series C instead of Series B", "Date Out of Window: Announced August 4, 2026", "Excluded: Acquisition by Stripe").
                   - 🟡 [UNVERIFIED - <Reason Incomplete>] — Surfaced in reporting, but retrieved evidence is insufficient/ambiguous to verify all mandatory fields.

                4. EPISTEMIC HUMILITY ON ZERO RESULTS:
                   - Distinguish "My retrieved evidence did not establish any qualifying companies" from an absolute claim that none exist.
                   - State clearly: "In the retrieved live web evidence across multi-hop search passes, 0 candidates strictly verified as [QUALIFIED] across all constraints. Below is the audited breakdown of candidates discovered, rejected, and unverified."

                5. ZERO CITATION LAUNDERING:
                   - No fabricated metrics or unverified multipliers. All links must be real markdown links to retrieved URLs.

                Output ONLY valid raw JSON with:
                - "thought": (Your final verification audit summary)
                - "action_type": "finish"
                - "final_response": (Your complete, exhaustive markdown deliverable for the founder adhering to all verification, provenance, and audit standards)
                '''
                tokens_in += estimate_tokens(final_prompt)
                try:
                    step3_res = generate_content_with_retry(
                        client=client,
                        model='gemini-3.5-flash',
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
                record.final_output = step2_plan.get('final_response') or final_res.text
        else:
            record.steps.append({
                'step_number': 1,
                'thought': thought,
                'tool_called': None,
                'tool_input': None,
                'tool_output': 'Direct synthesis completed'
            })
            record.final_output = plan.get('final_response', 'Task concluded successfully.')

        # Unpack JSON if final_output is still a JSON string
        if record.final_output and isinstance(record.final_output, str):
            parsed = parse_json_safely(record.final_output)
            if isinstance(parsed, dict) and parsed:
                if parsed.get('final_response'):
                    record.final_output = parsed['final_response']
                elif parsed.get('thought') and parsed.get('action_type') != 'call_tool':
                    record.final_output = parsed['thought']

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

def resume_approved_task(task_id: str, approved: bool, founder_feedback: Optional[str] = None) -> TaskRecord:
    record = get_task(task_id)
    if not record or record.status != 'waiting_approval':
        return record

    if not approved:
        record.status = 'rejected'
        record.final_output = f'Action rejected by founder. Feedback: {founder_feedback or "No feedback given."}'
        record.completed_at = datetime.utcnow().isoformat()
        save_task(record)
        return record

    # Approved: execute the pending tool call
    pending = record.pending_action or {}
    tool_name = pending.get('tool_name')
    tool_params = pending.get('tool_params') or {}

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
    return record
