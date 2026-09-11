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
Your Core Mission: {objective}
Your Behavioral Persona: {persona}

Your Standard Operating Procedures (SOPs):
{sops_formatted}

Available Tools:
{tools_formatted}

Current Task:
{task_prompt}

Analyze the task and determine the best action.
Respond in valid JSON with:
- "thought": (Your internal reasoning about what to do next based on your SOPs)
- "action_type": ("call_tool" or "finish")
- "tool_name": (Name of tool to call, or null if finishing)
- "tool_params": (Dictionary of tool parameters, or null)
- "final_response": (If finishing, provide your complete detailed briefing / deliverables for the founder)

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

    prompt = RUNNER_PROMPT_TEMPLATE.format(
        name=employee.name,
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

        if raw_text.startswith('`json'):
            raw_text = raw_text[7:]
        if raw_text.startswith('`'):
            raw_text = raw_text[3:]
        if raw_text.endswith('`'):
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

            # Secondary pass to synthesize final output or execute next tool with intelligence
            followup_prompt = f'''
            Based on the tool results:
            {json.dumps(tool_output, indent=2)}

            Provide your final complete deliverable and executive summary for the founder, or call the next tool if required by your SOPs.
            Output ONLY valid raw JSON adhering to the same schema (thought, action_type, tool_name, tool_params, final_response).
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
