import sqlite3
import json
import os
from typing import List, Optional
from app.models.employee import AIEmployeeSpec, TaskRecord

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'ai_employee.db')

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        department TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    ''')
    
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        employee_id TEXT NOT NULL,
        status TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    )
    ''')
    
    conn.commit()
    conn.close()
    seed_templates_if_empty()

def save_employee(employee: AIEmployeeSpec):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO employees (id, name, department, data, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (employee.id, employee.name, employee.department, json.dumps(employee.model_dump()), employee.created_at))
    conn.commit()
    conn.close()

def get_employee(employee_id: str) -> Optional[AIEmployeeSpec]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM employees WHERE id = ?', (employee_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return AIEmployeeSpec(**json.loads(row['data']))
    return None

def list_employees() -> List[AIEmployeeSpec]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM employees ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [AIEmployeeSpec(**json.loads(r['data'])) for r in rows]

def delete_employee(employee_id: str):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM employees WHERE id = ?', (employee_id,))
    cursor.execute('DELETE FROM tasks WHERE employee_id = ?', (employee_id,))
    conn.commit()
    conn.close()

def save_task(task: TaskRecord):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR REPLACE INTO tasks (id, employee_id, status, data, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (task.id, task.employee_id, task.status, json.dumps(task.model_dump()), task.created_at))
    conn.commit()
    conn.close()

def get_task(task_id: str) -> Optional[TaskRecord]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM tasks WHERE id = ?', (task_id,))
    row = cursor.fetchone()
    conn.close()
    if row:
        return TaskRecord(**json.loads(row['data']))
    return None

def list_tasks(limit: int = 50) -> List[TaskRecord]:
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT data FROM tasks ORDER BY created_at DESC LIMIT ?', (limit,))
    rows = cursor.fetchall()
    conn.close()
    return [TaskRecord(**json.loads(r['data'])) for r in rows]

def seed_templates_if_empty():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) as cnt FROM employees')
    count = cursor.fetchone()['cnt']
    conn.close()
    
    if count == 0:
        templates = [
            AIEmployeeSpec(
                id='emp_sdr_01',
                name='Maya Vance',
                role='B2B Sales Development Rep (SDR)',
                department='CRM',
                avatar_emoji='🎯',
                theme_color='emerald',
                objective='Identify ideal target accounts, research decision makers, and draft personalized high-converting cold outreach.',
                persona='Professional, concise, consultative, and hyper-personalized.',
                sops=[
                    '1. Search for target companies and their recent news or pain points.',
                    '2. Formulate a 3-sentence value proposition matching their industry.',
                    '3. Draft an email with a clear soft CTA (e.g. 15-min chat next Tuesday).',
                    '4. ALWAYS request approval before transmitting external emails.'
                ],
                tools=['web_search', 'email_sender', 'sheet_logger'],
                schedule_type='daily',
                requires_approval_for=['email_sender']
            ),
            AIEmployeeSpec(
                id='emp_hr_01',
                name='Arjun Patel',
                role='Talent & Resume Screening Specialist',
                department='HRM',
                avatar_emoji='📋',
                theme_color='indigo',
                objective='Parse applicant profiles, cross-reference required skills, score candidates, and draft interview invitations.',
                persona='Fair, empathetic, rigorous with technical and cultural criteria.',
                sops=[
                    '1. Review candidate profile against job specification requirements.',
                    '2. Calculate match score from 0-100 with objective pros and cons.',
                    '3. For candidates scoring >75, generate personalized screening interview invites.'
                ],
                tools=['web_search', 'email_sender', 'sheet_logger'],
                schedule_type='on_demand',
                requires_approval_for=['email_sender']
            ),
            AIEmployeeSpec(
                id='emp_mkt_01',
                name='Chloe Chen',
                role='Growth Marketing & Competitor Intel Analyst',
                department='Marketing',
                avatar_emoji='🚀',
                theme_color='purple',
                objective='Monitor industry trends, dissect competitor feature launches, and generate viral LinkedIn/Twitter thought leadership posts.',
                persona='Sharp, trend-aware, high-energy storytelling.',
                sops=[
                    '1. Search for breaking AI and market announcements in the specified niche.',
                    '2. Extract actionable takeaways for early-stage founders.',
                    '3. Draft 2 LinkedIn hook variations and a comprehensive thought leadership breakdown.'
                ],
                tools=['web_search', 'sheet_logger', 'slack_notifier'],
                schedule_type='interval',
                schedule_interval_mins=360,
                requires_approval_for=[]
            ),
            AIEmployeeSpec(
                id='emp_ops_01',
                name='David Kim',
                role='Operations & Cashflow Reconciliation Guard',
                department='Operations',
                avatar_emoji='⚡',
                theme_color='amber',
                objective='Detect overdue invoices, track vendor deliverables, and draft polite financial reminders.',
                persona='Organized, punctual, respectful yet firm on deadlines.',
                sops=[
                    '1. Audit payment statuses and flag items past due by >5 business days.',
                    '2. Prepare summary table of accounts receivable.',
                    '3. Draft reminder notes for client accounts.'
                ],
                tools=['sheet_logger', 'email_sender', 'slack_notifier'],
                schedule_type='daily',
                requires_approval_for=['email_sender']
            )
        ]
        for t in templates:
            save_employee(t)
