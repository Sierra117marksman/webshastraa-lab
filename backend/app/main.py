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
from app.models.memory import (
    MemoryRecord,
    AuditLogEntry,
    ToolPermission,
    CreateMemoryRequest,
    UpdateMemoryRequest,
    TaskFeedbackRequest,
)
from app.db.store import (
    init_db,
    save_employee,
    list_employees,
    get_employee,
    delete_employee,
    list_tasks,
    get_task,
    save_memory,
    get_memory,
    list_memories,
    list_active_memories,
    delete_memory,
    list_permissions,
    save_permission,
    save_audit_log,
    list_audit_log,
)
from app.engine.compiler import compile_prompt_to_employee
from app.engine.runner import run_employee_task, resume_approved_task
from app.engine.conflict_resolver import check_for_conflict, apply_supersession
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
    groq_api_key: Optional[str] = None
    smtp_user: Optional[str] = None
    smtp_pass: Optional[str] = None
    blacklist_domains: Optional[str] = None

@app.on_event('startup')
def on_startup():
    init_db()

@app.get('/')
def root():
    return {
        'status': 'online',
        'service': 'Webshastraa AI - Autonomous Employee Engine',
        'version': '1.0.0',
        'health': '/health',
        'docs': '/docs'
    }

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
    groq_key = os.getenv('GROQ_API_KEY', '')
    tavily_key = os.getenv('TAVILY_API_KEY', '')
    smtp_user = os.getenv('SMTP_USER', 'webshastraa@gmail.com')
    smtp_pass = os.getenv('SMTP_PASS', '')
    backup_user = os.getenv('BACKUP_SMTP_USER', '')
    blacklist_domains = os.getenv('BLACKLIST_DOMAINS', 'investor.com,board.com,vip.com,internal.com')
    
    active_sender = smtp_user if smtp_pass.strip() else (backup_user if backup_user else smtp_user)
    
    return {
        'groq_connected': bool(groq_key.strip()),
        'groq_key_preview': f'{groq_key[:6]}...{groq_key[-4:]}' if groq_key else '',
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
    if req.groq_api_key is not None:
        os.environ['GROQ_API_KEY'] = req.groq_api_key.strip()
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


@app.post('/api/tasks/{task_id}/feedback')
def submit_task_feedback(task_id: str, req: TaskFeedbackRequest):
    task = get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail='Task not found')
    proposed_memory = None
    if req.auto_create_memory and req.feedback.strip():
        try:
            from app.engine.reflector import generate_proposed_memory
            emp = get_employee(task.employee_id)
            if emp:
                proposed_memory = generate_proposed_memory(
                    employee_id=emp.id, employee_name=emp.name, employee_role=emp.role,
                    task_id=task_id, task_prompt=task.task_prompt,
                    what_happened=task.final_output or 'Completed task',
                    feedback=req.feedback, trigger_event='manual_feedback',
                )
                if proposed_memory:
                    save_memory(proposed_memory)
        except Exception:
            pass
    return {
        'task_id': task_id, 'feedback_recorded': True,
        'quality_rating': req.quality_rating,
        'proposed_memory': proposed_memory.model_dump() if proposed_memory else None,
    }


@app.get('/api/employees/{employee_id}/memories', response_model=List[MemoryRecord])
def get_employee_memories(employee_id: str, status: Optional[str] = None):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail='Employee not found')
    effective_status = None if status == 'all' else status
    return list_memories(employee_id, status=effective_status)


@app.post('/api/employees/{employee_id}/memories', response_model=MemoryRecord)
def create_memory(employee_id: str, req: CreateMemoryRequest):
    import uuid as _uuid
    from datetime import datetime as _dt
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail='Employee not found')
    now = _dt.utcnow().isoformat()
    memory = MemoryRecord(
        id=f'mem_{_uuid.uuid4().hex[:12]}', employee_id=employee_id,
        category=req.category, title=req.title, trigger_event=req.trigger_event,
        scope=req.scope, source='Founder (manual)',
        context=req.context, critique=req.critique, distilled_rule=req.distilled_rule,
        confidence_score=0.95, priority=req.priority, version=1,
        status='active', created_at=now, activated_at=now, last_confirmed_at=now,
    )
    conflict = check_for_conflict(memory)
    if conflict.has_conflict:
        memory.status = 'proposed'
    save_memory(memory)
    return memory


@app.patch('/api/memories/{memory_id}', response_model=MemoryRecord)
def update_memory(memory_id: str, req: UpdateMemoryRequest):
    from datetime import datetime as _dt
    memory = get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail='Memory not found')
    if req.title is not None:
        memory.title = req.title
    if req.distilled_rule is not None:
        memory.distilled_rule = req.distilled_rule
    if req.scope is not None:
        memory.scope = req.scope
    if req.priority is not None:
        memory.priority = req.priority
    if req.status == 'active' and memory.status == 'proposed':
        conflict = check_for_conflict(memory)
        if conflict.has_conflict and conflict.existing_rule:
            memory = apply_supersession(memory, conflict.existing_rule.id, founder_confirmed=True)
            return memory
        now = _dt.utcnow().isoformat()
        memory.status = 'active'
        memory.activated_at = now
        memory.last_confirmed_at = now
    elif req.status:
        memory.status = req.status
    memory.version += 1
    save_memory(memory)
    return memory


@app.delete('/api/memories/{memory_id}')
def remove_memory(memory_id: str):
    memory = get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail='Memory not found')
    delete_memory(memory_id)
    return {'deleted': memory_id}


@app.get('/api/employees/{employee_id}/permissions', response_model=List[ToolPermission])
def get_employee_permissions(employee_id: str):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail='Employee not found')
    return list_permissions(employee_id)


@app.put('/api/employees/{employee_id}/permissions/{tool_id}', response_model=ToolPermission)
def update_employee_permission(employee_id: str, tool_id: str, perm: ToolPermission):
    emp = get_employee(employee_id)
    if not emp:
        raise HTTPException(status_code=404, detail='Employee not found')
    save_permission(employee_id, perm)
    return perm


@app.get('/api/audit-log', response_model=List[AuditLogEntry])
def get_audit_log(employee_id: Optional[str] = None, task_id: Optional[str] = None, limit: int = 100):
    return list_audit_log(employee_id=employee_id, task_id=task_id, limit=limit)


@app.get('/api/analytics/today')
def get_today_stats():
    from datetime import datetime as _dt
    today_prefix = _dt.utcnow().strftime('%Y-%m-%d')
    all_tasks = list_tasks(limit=500)
    today_tasks = [t for t in all_tasks if (t.created_at or '').startswith(today_prefix)]
    employees = list_employees()
    awaiting = [t for t in today_tasks if t.status == 'waiting_approval']
    completed = [t for t in today_tasks if t.status == 'completed']
    failed = [t for t in today_tasks if t.status in ('failed', 'rejected')]
    total_cost = round(sum(getattr(t, 'cost_usd', 0.0) or 0.0 for t in today_tasks), 4)
    today_audit = [e for e in list_audit_log(limit=500) if e.timestamp.startswith(today_prefix)]
    per_employee = []
    for emp in employees:
        emp_tasks = [t for t in today_tasks if t.employee_id == emp.id]
        per_employee.append({
            'employee_id': emp.id, 'name': emp.name,
            'avatar_emoji': getattr(emp, 'avatar_emoji', '!'),
            'tasks_run': len(emp_tasks),
            'awaiting_approval': len([t for t in emp_tasks if t.status == 'waiting_approval']),
            'completed': len([t for t in emp_tasks if t.status == 'completed']),
            'active_memories': len(list_active_memories(emp.id)),
        })
    return {
        'date': today_prefix, 'employees_total': len(employees),
        'tasks_awaiting_approval': len(awaiting),
        'tasks_completed': len(completed), 'tasks_failed': len(failed),
        'total_ai_cost_usd': total_cost,
        'lessons_learned_today': len([e for e in today_audit if e.event_type == 'memory_activated']),
        'proposed_memories_pending': len([e for e in today_audit if e.event_type == 'reflection_proposed']),
        'per_employee': per_employee,
    }
