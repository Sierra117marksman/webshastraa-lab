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
  session_id?: string | null;
  resume_state?: string | null;
  task_prompt: string;
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed' | 'rejected' | string;
  steps: TaskStep[];
  pending_action?: {
    action?: string;
    tool_name: string;
    permission?: string;
    reason?: string;
    candidate_id?: string;
    company_name?: string;
    canonical_domain?: string;
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

export interface CandidateBadge {
  symbol: string;
  label: string;
  status: 'SUPPORTED' | 'UNVERIFIED' | 'NOT_AUDITED' | 'CONTRADICTED' | string;
  field: string;
}

export interface ResearchEvidenceItem {
  id: string;
  verifier_version: string;
  source_url: string;
  source_type: string;
  supports_field: string;
  signal_type: string;
  extracted_value: string;
  raw_excerpt: string;
  content_hash: string;
  confidence: 'HIGH' | 'MEDIUM' | 'LOW' | string;
  financial_period?: string | null;
  retrieved_at: string;
}

export interface ResearchClaimItem {
  id: string;
  field: string;
  value?: string | null;
  status: 'SUPPORTED' | 'UNSUPPORTED' | 'CONTRADICTED' | 'UNVERIFIED' | 'NOT_AUDITED' | string;
  notes?: string | null;
  version: number;
  updated_at: string;
}

export interface ResearchOutreachDraft {
  to: string;
  subject: string;
  body: string;
  allowed_claims: Record<string, unknown>;
  blocked_claims: Record<string, string>;
}

export interface ResearchCandidate {
  id: string;
  company_name: string;
  canonical_domain: string;
  initial_url: string;
  final_url?: string | null;
  discovery_hop: number;
  http_reachable?: boolean | null;
  http_status?: number | null;
  page_available?: boolean | null;
  storefront_state: string;
  audited_by_verifier: boolean;
  qualification_status: 'PENDING' | 'VERIFIED' | 'PROSPECT' | 'REJECTED' | string;
  rejection_reason?: string | null;
  evidence_count: number;
  claims_count: number;
  badges: CandidateBadge[];
  evidence: ResearchEvidenceItem[];
  claims: ResearchClaimItem[];
  decision?: {
    id: string;
    hop: number;
    result: string;
    decision_hash: string;
    requirement_results: Record<string, unknown>;
    rejection_reason?: string | null;
    created_at: string;
  } | null;
  outreach_draft?: ResearchOutreachDraft | null;
}

export interface PendingApprovalContext {
  required: boolean;
  candidate_id?: string | null;
  company_name: string;
  canonical_domain: string;
  action: string;
  tool_name: string;
  permission: string;
  reason: string;
  explanation: string;
  to: string;
  subject: string;
  body: string;
}

export interface TaskResearchLedger {
  task_id: string;
  session_id: string;
  employee_id: string;
  employee_name: string;
  task_status: string;
  session_status: string;
  raw_prompt: string;
  target_verified_leads: number;
  current_hop: number;
  max_hops: number;
  termination_reason: string;
  current_stage_label: string;
  metrics: {
    target: number;
    candidates: number;
    audited: number;
    verified: number;
    prospects: number;
    rejected: number;
    pending: number;
  };
  requirements: {
    id: string;
    field: string;
    operator: string;
    expected: unknown;
    priority: string;
    on_unknown: string;
    observability_class: string;
  }[];
  candidates: ResearchCandidate[];
  pending_approval?: PendingApprovalContext | null;
}

