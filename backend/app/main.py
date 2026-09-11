import os
from dotenv import load_dotenv

# Load env before importing app modules
ENV_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(ENV_PATH)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Optional
from pydantic import BaseModel

from app.models.employee import (
    AIEmployeeSpec,
    CompilePromptRequest,
    DispatchTaskRequest,
    ApprovalActionRequest,
    TaskRecord
)
from app.db.store import (
    init_db,
    save_employee,
    list_employees,
    get_employee,
    delete_employee,
    list_tasks,
    get_task
)
from app.engine.compiler import compile_prompt_to_employee
from app.engine.runner import run_employee_task, resume_approved_task
from app.tools.registry import TOOLS_METADATA

app = FastAPI(title='Webshastraa AI - Autonomous Employee Engine', version='1.0.0')

app.add_middleware(
    CORSMiddleware,
    allow_origins=['*'],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

class SettingsUpdate(BaseModel):
    tavily_api_key: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    blacklist_domains: Optional[str] = None

@app.on_event('startup')
def on_startup():
    init_db()

@app.get('/health')
def health():
    return {'status': 'online', 'service': 'ai-employee-engine'}

@app.get('/api/analytics')
def get_analytics():
    tasks = list_tasks(limit=200)
    completed = [t for t in tasks if t.status == 'completed']
    hours_saved = round(len(completed) * 0.35, 1)  # ~21 mins saved per task
    total_cost = round(sum(getattr(t, 'cost_usd', 0.0004) or 0.0004 for t in tasks), 4)
    human_cost = round(hours_saved * 25.0, 2)  # Benchmark $25/hr virtual assistant
    net_savings = round(max(0.0, human_cost - total_cost), 2)
    return {
        'total_tasks': len(tasks),
        'completed_tasks': len(completed),
        'hours_saved': hours_saved,
        'total_cost_usd': total_cost,
        'human_cost_equivalent_usd': human_cost,
        'net_savings_usd': net_savings
    }

@app.get('/api/settings')
def get_settings():
    tavily_key = os.getenv('TAVILY_API_KEY', '')
    smtp_user = os.getenv('SMTP_USER', 'webshastraa@gmail.com')
    smtp_pass = os.getenv('SMTP_PASS', '')
    backup_user = os.getenv('BACKUP_SMTP_USER', '')
    blacklist_domains = os.getenv('BLACKLIST_DOMAINS', 'investor.com,board.com,vip.com,internal.com')
    
    active_sender = smtp_user if smtp_pass.strip() else (backup_user if backup_user else smtp_user)
    
    return {
        'gemini_connected': bool(os.getenv('GEMINI_API_KEY')),
        'tavily_connected': bool(tavily_key.strip()),
        'tavily_key_preview': f'{tavily_key[:6]}...' if tavily_key else '',
        'smtp_user': smtp_user,
        'smtp_has_pass': bool(smtp_pass.strip()),
        'active_email_sender': active_sender,
        'smtp_active': bool(smtp_pass.strip() or os.getenv('BACKUP_SMTP_PASS')),
        'blacklist_domains': blacklist_domains
    }

@app.post('/api/settings')
def update_settings(req: SettingsUpdate):
    if req.tavily_api_key is not None:
        os.environ['TAVILY_API_KEY'] = req.tavily_api_key.strip()
    if req.smtp_user is not None:
        os.environ['SMTP_USER'] = req.smtp_user.strip()
    if req.smtp_pass is not None:
        os.environ['SMTP_PASS'] = req.smtp_pass.strip()
    if req.blacklist_domains is not None:
        os.environ['BLACKLIST_DOMAINS'] = req.blacklist_domains.strip()
        
    return {'status': 'updated', 'settings': get_settings()}

@app.get('/api/tools')
def get_tools():
    return TOOLS_METADATA

@app.post('/api/compiler/compile', response_model=AIEmployeeSpec)
def compile_prompt(req: CompilePromptRequest):
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail='Prompt cannot be empty.')
    try:
        employee_spec = compile_prompt_to_employee(req.prompt)
        return employee_spec
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Compilation failed: {str(e)}')

@app.get('/api/employees', response_model=List[AIEmployeeSpec])
def get_all_employees():
    return list_employees()

@app.post('/api/employees', response_model=AIEmployeeSpec)
def create_employee(employee: AIEmployeeSpec):
    save_employee(employee)
    return employee

@app.delete('/api/employees/{employee_id}')
def remove_employee(employee_id: str):
    delete_employee(employee_id)
    return {'deleted': employee_id}

@app.post('/api/employees/{employee_id}/dispatch', response_model=TaskRecord)
def dispatch_task(employee_id: str, req: DispatchTaskRequest):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail='Employee not found')
    
    prompt = req.task_prompt or emp.objective
    task = run_employee_task(emp, prompt)
    return task

@app.get('/api/tasks', response_model=List[TaskRecord])
def get_task_history():
    return list_tasks(limit=50)

@app.post('/api/tasks/{task_id}/approve', response_model=TaskRecord)
def approve_action(task_id: str, req: ApprovalActionRequest):
    task = resume_approved_task(task_id, req.approved, req.feedback)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found or not awaiting approval')
    return task
