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
