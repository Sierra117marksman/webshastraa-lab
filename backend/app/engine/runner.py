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
1. TEMPORAL BOUNDING: Today is {current_date}. If the user prompt requests events from a relative timeframe (e.g., 'last month', 'recent', 'this week') or specific date window (e.g., 'between August 15 and September 10, 2026'), strictly compute and adhere to that exact window. Do NOT include older companies or earlier funding rounds simply because they are famous.
2. ZERO CITATION LAUNDERING: Never invent or assert specific quantitative statistics (e.g. '3.4x faster', '65% cycle time reduction') without an explicit named company case study, whitepaper, or primary source URL. If an observation is conceptual or qualitative, state it as a strategic thesis, not an empirical benchmark.
3. ENTITY PROVENANCE: When citing funding rounds, valuations, or company milestones, establish the complete verification chain: Company -> Funding Event -> Announcement Date -> Disclosed Amount -> Valuation -> Primary Source Link.
4. ADVERSARIAL AUDIT & REJECTION PROTOCOL:
   - When asked to audit claims or find companies meeting strict criteria:
   - State the exact evidence for every verified claim.
   - Explicitly list unsupported or out-of-window candidates as REJECTED with the exact reason (e.g., 'REJECTED: Sierra - round announced May 2026, outside target window').
   - If fewer than the requested number qualify, return ONLY the qualified ones. Never substitute or hallucinate older companies to fill a quota!
5. METHODOLOGICAL TRANSPARENCY: When asked for a ranking (e.g., 'top 3', '5 largest'), explicitly state your ranking methodology (e.g., 'Ranked strictly by highest disclosed funding amount in USD in descending order; acquisitions excluded').

Analyze the task and determine the best action.
Respond in valid JSON with:
- "thought": (Your internal reasoning about what to do next based on your SOPs and verification standards)
- "action_type": ("call_tool" or "finish")
- "tool_name": (Name of tool to call, or null if finishing)
- "tool_params": (Dictionary of tool parameters, or null)
- "final_response": (If finishing, provide your complete detailed briefing / deliverables for the founder adhering to verification standards)

Output ONLY raw parseable JSON. No markdown code blocks.
'''

def execute_tool_call(tool_name: str, params: Dict[str, Any]) -> Dict[str, Any]:
    if tool_name == 'web_search':
        return execute_web_search(params.get('query', ''))
    elif tool_name == 'email_sender':
        return execute_email_sender(params.get('to', ''), params.get('subject', ''), params.get('body', ''))
    elif tool_name == 'sheet_logger':
        return execute_sheet_logger(params.get('table', 'general_records'), params.get('record', {}))
    elif tool_name == 'slack_notifier':
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
            model='gemini-3.6-flash',
            contents=[{'role': 'user', 'parts': [{'text': prompt}]}]
        )

        raw_text = response.text.strip()
        tokens_out += estimate_tokens(raw_text)

        if raw_text.startswith('```json'):
            raw_text = raw_text[7:]
        if raw_text.startswith('```'):
            raw_text = raw_text[3:]
        if raw_text.endswith('```'):
            raw_text = raw_text[:-3]
        plan = json.loads(raw_text.strip())

        thought = plan.get('thought', 'Analyzing request...')
        action_type = plan.get('action_type', 'finish')
        tool_name = plan.get('tool_name')
        tool_params = plan.get('tool_params') or {}

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
            1. TEMPORAL ACCURACY: Verify that every mentioned company, event, or funding round strictly falls inside the requested timeframe relative to {current_date}. Explicitly list the actual announcement date (e.g. Month Day, Year).
            2. STRUCTURED VERIFICATION TABLE:
               | Rank | Company | Round | Disclosed USD Amount | Announcement Date | Primary Source Link |
            3. RANKING METHODOLOGY: Declare the explicit ranking metric (e.g. "Ranked strictly by disclosed USD amount in descending order; acquisitions excluded").
            4. FACTUAL CLAIM AUDIT (CRITICAL):
               If the task requires auditing, date bounding, or strict verification, provide a dedicated "Factual Claim Audit":
               - State each candidate entity and the exact primary source evidence supporting it.
               - Explicitly mark disqualified/unsupported claims or entities as [REJECTED] with the reason (e.g. "REJECTED: Sierra - announced May 2026, outside August 15 - September 10 window").
               - If fewer qualify than requested, return fewer. Never substitute older prominent companies to fill the quota.
            5. ZERO UNSOURCED METRICS: Do not invent unverified percentages (e.g. "65% cycle time") or multipliers (e.g. "3.4x") without a named company report or study. If sharing an observational takeaway, label it clearly as an executive insight.
            6. PRIMARY EVIDENCE: Include markdown links to source URLs retrieved in the live search.
            7. STRATEGIC SYNTHESIS: Provide sharp, founder-ready takeaways and marketing copy grounded directly in the verified facts above.

            Output ONLY valid raw JSON adhering to the schema (thought, action_type, tool_name, tool_params, final_response).
            '''
            tokens_in += estimate_tokens(followup_prompt)
            final_res = generate_content_with_retry(
                client=client,
                model='gemini-3.6-flash',
                contents=[
                    {'role': 'user', 'parts': [{'text': prompt}]},
                    {'role': 'model', 'parts': [{'text': raw_text}]},
                    {'role': 'user', 'parts': [{'text': followup_prompt}]}
                ]
            )

            tokens_out += estimate_tokens(final_res.text)
            clean_text = final_res.text.strip()
            if clean_text.startswith('```json'):
                clean_text = clean_text[7:]
            if clean_text.startswith('```'):
                clean_text = clean_text[3:]
            if clean_text.endswith('```'):
                clean_text = clean_text[:-3]

            try:
                step2_plan = json.loads(clean_text.strip())
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
                    record.final_output = step2_plan.get('final_response') or f'Tool {step2_tool} executed successfully.'
                else:
                    record.final_output = step2_plan.get('final_response') or final_res.text
            except Exception:
                record.final_output = final_res.text
        else:
            record.steps.append({
                'step_number': 1,
                'thought': thought,
                'tool_called': None,
                'tool_input': None,
                'tool_output': 'Direct synthesis completed'
            })
            record.final_output = plan.get('final_response', 'Task concluded successfully.')

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
