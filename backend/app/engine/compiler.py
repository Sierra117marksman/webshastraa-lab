import os
import json
import uuid
from google import genai
from app.models.employee import AIEmployeeSpec
from app.engine.gemini_client import generate_content_with_retry

COMPILER_SYSTEM_INSTRUCTION = '''
You are the Meta-Agent Architect for an autonomous AI Employee platform.
Your job is to take a founder's simple, plain-English prompt and compile it into a complete, enterprise-ready Autonomous AI Employee specification.

Output ONLY a valid JSON object with these exact keys:
- name: (Creative realistic professional human name, e.g. 'Elena Rostova', 'Marcus Vance')
- role: (Job title, e.g. 'Outbound B2B SDR', 'Technical Recruiting Screener')
- department: (Must be exactly one of: 'Marketing', 'HRM', 'CRM', 'Operations')
- avatar_emoji: (A single fitting emoji like 🎯, 🚀, 📋, ⚡, 🔍, 📊)
- theme_color: (One of: 'blue', 'purple', 'emerald', 'amber', 'rose', 'indigo')
- objective: (A clear, outcome-oriented 1-2 sentence mission statement)
- persona: (Tone, communication style, behavioral traits)
- sops: (A list of 3-5 concrete step-by-step Standard Operating Procedures the employee must follow)
- tools: (List of tool IDs from: ['web_search', 'email_sender', 'sheet_logger', 'slack_notifier'])
- schedule_type: (One of: 'on_demand', 'daily', 'interval')
- schedule_interval_mins: (Integer or null, e.g. 60 or 360)
- requires_approval_for: (Sub-list of tools that need human sign-off, e.g. ['email_sender'])

Do NOT include any markdown code blocks (like `json), commentary, or extra text. Output ONLY raw parseable JSON.
'''

def compile_prompt_to_employee(user_prompt: str) -> AIEmployeeSpec:
    api_key = os.getenv('GEMINI_API_KEY')
    client = genai.Client(api_key=api_key)
    
    response = generate_content_with_retry(
        client=client,
        model='gemini-3.8-flash',
        contents=[
            {'role': 'user', 'parts': [{'text': f'{COMPILER_SYSTEM_INSTRUCTION}\n\nFounder Prompt: {user_prompt}'}]}
        ]
    )
    
    raw_text = response.text.strip()
    if raw_text.startswith('`json'):
        raw_text = raw_text[7:]
    if raw_text.startswith('`'):
        raw_text = raw_text[3:]
    if raw_text.endswith('`'):
        raw_text = raw_text[:-3]
    raw_text = raw_text.strip()
    
    data = json.loads(raw_text)
    
    employee_id = f"emp_{str(uuid.uuid4())[:8]}"
    return AIEmployeeSpec(
        id=employee_id,
        name=data.get('name', 'AI Specialist'),
        role=data.get('role', 'Autonomous Agent'),
        department=data.get('department', 'Operations'),
        avatar_emoji=data.get('avatar_emoji', '🤖'),
        theme_color=data.get('theme_color', 'blue'),
        objective=data.get('objective', user_prompt),
        persona=data.get('persona', 'Thorough, analytical, and execution-oriented.'),
        sops=data.get('sops', ['1. Analyze objective.', '2. Execute actions.', '3. Report results.']),
        tools=data.get('tools', ['web_search', 'sheet_logger']),
        schedule_type=data.get('schedule_type', 'on_demand'),
        schedule_interval_mins=data.get('schedule_interval_mins'),
        requires_approval_for=data.get('requires_approval_for', ['email_sender'])
    )
