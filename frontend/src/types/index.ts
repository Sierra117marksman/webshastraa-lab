export interface AIEmployeeSpec {
  id: string;
  name: string;
  role: string;
  department: 'Marketing' | 'HRM' | 'CRM' | 'Operations' | string;
  avatar_emoji: string;
  theme_color: string;
  objective: string;
  persona: string;
  sops: string[];
  tools: string[];
  schedule_type: 'on_demand' | 'daily' | 'interval' | string;
  schedule_interval_mins?: number;
  requires_approval_for: string[];
  status: 'active' | 'paused' | string;
  created_at: string;
}

export interface TaskStep {
  step_number: number;
  thought: string;
  tool_called?: string;
  tool_input?: unknown;
  tool_output?: unknown;
  timestamp: string;
}

export interface TaskRecord {
  id: string;
  employee_id: string;
  employee_name: string;
  task_prompt: string;
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'rejected' | string;
  steps: TaskStep[];
  pending_action?: {
    tool_name: string;
    tool_params: Record<string, unknown>;
    explanation: string;
  };
  final_output?: string;
  tokens_used?: number;
  cost_usd?: number;
  time_saved_mins?: number;
  created_at: string;
  completed_at?: string;
}

export interface SettingsState {
  groq_connected?: boolean;
  groq_key_preview?: string;
  gemini_connected: boolean;
  tavily_connected: boolean;
  tavily_key_preview: string;
  smtp_user: string;
  smtp_has_pass: boolean;
  active_email_sender: string;
  smtp_active: boolean;
  blacklist_domains?: string;
}

export interface AnalyticsData {
  total_tasks: number;
  completed_tasks: number;
  hours_saved: number;
  total_cost_usd: number;
  human_cost_equivalent_usd: number;
  net_savings_usd: number;
}

export type PermissionScope = 'READ' | 'ANALYZE' | 'DRAFT' | 'REQUEST' | 'EXECUTE';

export interface ToolPermission {
  tool_id: string;
  permission: PermissionScope;
  requires_approval: boolean;
  notes?: string | null;
}

export type MemoryCategory = 'mistake_avoided' | 'learned_rule' | 'proven_playbook' | 'founder_preference';
export type MemoryStatus = 'proposed' | 'active' | 'superseded' | 'rejected';

export interface MemoryRecord {
  id: string;
  employee_id: string;
  category: MemoryCategory;
  title: string;
  trigger_event: string;
  scope: string;
  source: string;
  context: string;
  critique: string;
  distilled_rule: string;
  confidence_score: number;
  priority: number;
  version: number;
  supersedes?: string | null;
  status: MemoryStatus;
  created_at: string;
  last_confirmed_at?: string | null;
  activated_at?: string | null;
}

export interface AuditLogEntry {
  id: string;
  employee_id: string;
  task_id: string;
  event_type: string;
  prompt_version?: string | null;
  memories_used: string[];
  tools_called: string[];
  decision?: string | null;
  output_summary: string;
  founder_feedback?: string | null;
  final_action?: string | null;
  cost_usd: number;
  tokens_used: number;
  timestamp: string;
}

export interface TodayStats {
  date: string;
  employees_total: number;
  tasks_awaiting_approval: number;
  tasks_completed: number;
  tasks_failed: number;
  total_ai_cost_usd: number;
  lessons_learned_today: number;
  proposed_memories_pending: number;
  per_employee: {
    employee_id: string;
    name: string;
    avatar_emoji: string;
    tasks_run: number;
    awaiting_approval: number;
    completed: number;
    active_memories: number;
  }[];
}
