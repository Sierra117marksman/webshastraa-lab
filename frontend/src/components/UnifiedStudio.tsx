'use client';

import React, { useState, useEffect } from 'react';
import {
  Sparkles,
  Send,
  Check,
  X,
  FileText,
  Terminal,
  Copy,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Mail,
  ShieldCheck,
  Sliders,
  MessageSquare,
  Settings2,
  Clock,
  DollarSign,
  Zap
} from 'lucide-react';
import { AIEmployeeSpec, TaskRecord, AuditLogEntry } from '@/types';
import MarkdownViewer from './MarkdownViewer';
import ExecutionMonitor from './ExecutionMonitor';
import MemoryVault from './MemoryVault';
import PermissionPanel from './PermissionPanel';

interface UnifiedStudioProps {
  employees: AIEmployeeSpec[];
  tasks: TaskRecord[];
  apiBase: string;
  activeEmailSender: string;
  onDispatch: (employeeId: string, prompt?: string) => Promise<void>;
  onApprove: (taskId: string, approved: boolean, feedback?: string) => Promise<void>;
  dispatchingId: string | null;
}

interface AgentHumanGuide {
  shortTag: string;
  tagColor: string;
  whatIDo: string;
  toolsSummary: string[];
  safetyNote: string;
  quickChips: string[];
}

const HUMAN_GUIDES: Record<string, AgentHumanGuide> = {
  CRM: {
    shortTag: 'Sales & Cold Emails',
    tagColor: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    whatIDo: 'Finds verified companies, checks their live website tech stack (Shopify, WooCommerce, apps), and drafts personalized cold emails.',
    toolsSummary: ['🔍 Google & Web Search', '🌐 Live Website & App Verifier', '📊 CRM Lead Scorer', '✉️ Gmail Cold Outreach'],
    safetyNote: 'Never sends an email without your 1-click approval.',
    quickChips: [
      'Find 10 Indian D2C brands on Shopify using paid apps and draft cold outreach',
      'Find 5 D2C skincare brands on Shopify and verify their installed apps',
      'Audit domain tech stack for velnoir.com and draft a consultative founder email'
    ]
  },
  Marketing: {
    shortTag: 'Content & LinkedIn',
    tagColor: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
    whatIDo: 'Researches live industry trends, analyzes competitor positioning, and writes high-converting LinkedIn posts & hooks.',
    toolsSummary: ['🔍 Trend & News Search', '✍️ Viral Hook Generator', '📈 Competitor Positioning Analyzer'],
    safetyNote: 'Drafts content directly in your workspace for review.',
    quickChips: [
      'Write 3 viral LinkedIn hooks about why slow Shopify stores lose D2C sales',
      'Find 5 trending topics in AI automation and draft a founder LinkedIn post',
      'Analyze top D2C brand storytelling angles and give 3 actionable templates'
    ]
  },
  HRM: {
    shortTag: 'Hiring & Talent',
    tagColor: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    whatIDo: 'Searches across job boards and directories to find companies hiring, screens candidates against scorecards, and drafts interview invites.',
    toolsSummary: ['🔍 Multi-Hop Job & Talent Search', '📋 Candidate Scorecard Evaluator', '✉️ Interview Invite Drafter'],
    safetyNote: 'Requires your approval before sending any external emails.',
    quickChips: [
      'Find 5 Indian D2C brands currently hiring Shopify or ecommerce developers',
      'Create a technical screening scorecard for a Senior React & Next.js engineer',
      'Draft interview invitation emails for shortlisted frontend candidates'
    ]
  },
  Operations: {
    shortTag: 'Finance & Invoices',
    tagColor: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    whatIDo: 'Audits vendor invoices for math errors, checks contractor billable hours against monthly caps, and flags billing anomalies.',
    toolsSummary: ['🧮 Invoice Math Verifier', '📑 Contractor Rate & Cap Checker', '⚠️ Anomaly Alerting'],
    safetyNote: 'Holds any billing dispute emails for founder sign-off.',
    quickChips: [
      'Audit submitted vendor invoices for mathematical errors and tax discrepancies',
      'Reconcile contractor billable hours against monthly budget caps',
      'Flag suspicious SaaS & Shopify app subscription charges and draft inquiry'
    ]
  }
};

export default function UnifiedStudio({
  employees,
  tasks,
  apiBase,
  activeEmailSender,
  onDispatch,
  onApprove,
  dispatchingId
}: UnifiedStudioProps) {
  // 'auto' or employee.id
  const [selectedId, setSelectedId] = useState<string>('crm_lead_gen');
  const [promptMode, setPromptMode] = useState<'guided' | 'freeform'>('guided');
  const [freeformPrompt, setFreeformPrompt] = useState<string>('');
  const [autoRoutedNotice, setAutoRoutedNotice] = useState<string | null>(null);

  // Guided Builder (Option C) state
  // CRM (Maya) fields
  const [crmNiche, setCrmNiche] = useState('Indian D2C Skincare & Fashion');
  const [crmPlatform, setCrmPlatform] = useState('Shopify');
  const [crmSignals, setCrmSignals] = useState('Paying for apps (Wati, Loox, Nudgify, Judge.me)');
  const [crmRevenue, setCrmRevenue] = useState('₹10 Lakh to ₹50 Lakh annual turnover profile');
  const [crmCount, setCrmCount] = useState('5');
  const [crmGoal, setCrmGoal] = useState('Verify live websites and draft cold outreach email');

  // Marketing (Chloe) fields
  const [mktTopic, setMktTopic] = useState('How slow Shopify storefronts silently kill D2C conversion rates');
  const [mktFormat, setMktFormat] = useState('3 LinkedIn Hooks + 1 Full Founder Post');
  const [mktTone, setMktTone] = useState('Direct, insightful founder voice with zero fluff');

  // HRM (Arjun) fields
  const [hrRole, setHrRole] = useState('Shopify / Ecommerce Developer');
  const [hrMarket, setHrMarket] = useState('India (Remote or Hybrid)');
  const [hrGoal, setHrGoal] = useState('Find companies actively hiring this role and list decision-makers');

  // Operations (David) fields
  const [opsTask, setOpsTask] = useState('Audit vendor invoices for math and tax discrepancies');
  const [opsDetails, setOpsDetails] = useState('Check line-item totals, GST calculations, and monthly retainer caps');

  // Output viewer state
  const [outputTab, setOutputTab] = useState<'deliverable' | 'steps'>('deliverable');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [rejectionFeedback, setRejectionFeedback] = useState<Record<string, string>>({});
  const [showRejectInput, setShowRejectInput] = useState<Record<string, boolean>>({});
  const [isBrainDrawerOpen, setIsBrainDrawerOpen] = useState(false);
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);

  // Resolve selected employee object
  const activeEmployee: AIEmployeeSpec | undefined =
    selectedId === 'auto'
      ? employees[0]
      : employees.find((e) => e.id === selectedId) || employees[0];

  // Ensure selectedId points to a valid employee once loaded
  useEffect(() => {
    if (employees.length > 0 && selectedId !== 'auto' && !employees.some((e) => e.id === selectedId)) {
      setSelectedId(employees[0].id);
    }
  }, [employees, selectedId]);

  // Load audit log for active employee
  useEffect(() => {
    if (!activeEmployee) return;
    let isMounted = true;
    const loadAudit = async () => {
      try {
        const res = await fetch(`${apiBase}/api/audit-log?employee_id=${activeEmployee.id}&limit=30`);
        if (res.ok) {
          const data = await res.json();
          if (isMounted) setAuditLog(data);
        }
      } catch {
        // Ignore transient network errors
      }
    };
    loadAudit();
    const interval = setInterval(loadAudit, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [apiBase, activeEmployee]);

  // Compute Guided Recipe Prompt dynamically based on active department
  const buildGuidedPrompt = (): string => {
    const dept = activeEmployee?.department || 'CRM';
    if (dept === 'CRM' || selectedId === 'auto') {
      return `Find ${crmCount} ${crmNiche} brands running on ${crmPlatform} with ${crmSignals} (${crmRevenue}). ${crmGoal}. Remember: mark private unverified turnover as UNVERIFIED rather than guessing.`;
    }
    if (dept === 'Marketing') {
      return `Topic: "${mktTopic}". Deliverable format: ${mktFormat}. Tone & style: ${mktTone}. Back up insights with live web research.`;
    }
    if (dept === 'HRM') {
      return `Target Role: ${hrRole} in ${hrMarket}. Objective: ${hrGoal}. Use multi-hop search across job boards, company pages, and directories.`;
    }
    return `Operations Audit Task: ${opsTask}. Focus areas: ${opsDetails}. Flag any anomalies clearly.`;
  };

  // Auto-router classifier for Freeform or Auto mode
  const pickBestEmployeeForPrompt = (text: string): AIEmployeeSpec => {
    const lower = text.toLowerCase();
    if (
      lower.includes('linkedin') ||
      lower.includes('content') ||
      lower.includes('post') ||
      lower.includes('hook') ||
      lower.includes('marketing') ||
      lower.includes('trend')
    ) {
      return employees.find((e) => e.department === 'Marketing') || employees[0];
    }
    if (
      lower.includes('hire') ||
      lower.includes('hiring') ||
      lower.includes('candidate') ||
      lower.includes('job') ||
      lower.includes('resume') ||
      lower.includes('applicant')
    ) {
      return employees.find((e) => e.department === 'HRM') || employees[0];
    }
    if (
      lower.includes('invoice') ||
      lower.includes('billing') ||
      lower.includes('finance') ||
      lower.includes('contractor') ||
      lower.includes('math') ||
      lower.includes('budget')
    ) {
      return employees.find((e) => e.department === 'Operations') || employees[0];
    }
    return employees.find((e) => e.department === 'CRM') || employees[0];
  };

  const handleRunTask = async (overridePrompt?: string) => {
    if (!employees.length) return;
    const rawPrompt =
      overridePrompt !== undefined
        ? overridePrompt
        : promptMode === 'guided'
        ? buildGuidedPrompt()
        : freeformPrompt;

    if (!rawPrompt.trim()) return;

    let targetEmp = activeEmployee || employees[0];
    if (selectedId === 'auto') {
      targetEmp = pickBestEmployeeForPrompt(rawPrompt);
      setAutoRoutedNotice(`Smart Auto-Router assigned this task to ${targetEmp.name} (${targetEmp.department})`);
      setSelectedId(targetEmp.id);
      setTimeout(() => setAutoRoutedNotice(null), 6000);
    }

    setSelectedTaskId(null); // Focus on newest task
    await onDispatch(targetEmp.id, rawPrompt);
    if (promptMode === 'freeform' && !overridePrompt) {
      setFreeformPrompt('');
    }
  };

  // Filter tasks for the currently viewed employee (or all if auto)
  const visibleTasks =
    selectedId === 'auto'
      ? tasks
      : tasks.filter((t) => t.employee_id === activeEmployee?.id);

  const activeTask = selectedTaskId
    ? visibleTasks.find((t) => t.id === selectedTaskId) || visibleTasks[0]
    : visibleTasks[0];

  const pendingApprovals = visibleTasks.filter((t) => t.status === 'waiting_approval');

  const guide: AgentHumanGuide =
    HUMAN_GUIDES[activeEmployee?.department || 'CRM'] || HUMAN_GUIDES.CRM;

  const handleCopyOutput = () => {
    if (!activeTask?.final_output) return;
    navigator.clipboard.writeText(activeTask.final_output);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className="space-y-6 animate-in fade-in duration-300 pb-16">
      {/* Auto-Router Toast Notification */}
      {autoRoutedNotice && (
        <div className="rounded-2xl bg-indigo-500/15 border border-indigo-500/40 px-4 py-3 text-xs text-indigo-200 flex items-center justify-between shadow-lg">
          <div className="flex items-center gap-2">
            <Sparkles className="w-4 h-4 text-indigo-400 shrink-0" />
            <span className="font-semibold">{autoRoutedNotice}</span>
          </div>
          <button
            type="button"
            onClick={() => setAutoRoutedNotice(null)}
            className="text-indigo-300 hover:text-white text-[11px] cursor-pointer"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* MAIN 2-COLUMN UNIFIED STUDIO */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
        
        {/* ==================== LEFT COLUMN: STEP 1 — PICK WHO WORKS ==================== */}
        <div className="lg:col-span-4 space-y-3 bg-[#0b0f1a]/90 border border-white/[0.08] rounded-3xl p-4 sm:p-5 shadow-xl">
          <div className="flex items-center justify-between pb-2 border-b border-white/[0.06]">
            <div>
              <span className="text-[10px] font-extrabold uppercase tracking-wider text-indigo-400 block">
                Step 1 • Choose Specialist
              </span>
              <h2 className="text-sm font-black text-white">Who Should Do This Work?</h2>
            </div>
            <span className="text-[11px] text-emerald-400 font-semibold flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
              {employees.length} Ready
            </span>
          </div>

          {/* Smart Auto-Router Card */}
          <button
            type="button"
            onClick={() => {
              setSelectedId('auto');
              setPromptMode('freeform');
            }}
            className={`w-full text-left p-3.5 rounded-2xl border transition cursor-pointer ${
              selectedId === 'auto'
                ? 'bg-gradient-to-r from-indigo-600/25 to-violet-600/15 border-indigo-500/60 shadow-lg shadow-indigo-500/10'
                : 'bg-white/[0.02] hover:bg-white/[0.05] border-white/[0.07]'
            }`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <div className="w-9 h-9 rounded-xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-lg">
                  ✨
                </div>
                <div>
                  <div className="text-xs font-extrabold text-white">Smart Auto-Router</div>
                  <div className="text-[11px] text-zinc-400">Not sure who to pick? Type any goal</div>
                </div>
              </div>
              <span className="text-[10px] font-bold px-2 py-0.5 rounded-md bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                Auto
              </span>
            </div>
          </button>

          {/* 4 Specialist Cards with Clear Plain-English Roles */}
          <div className="space-y-2.5 pt-1">
            {employees.map((emp) => {
              const empGuide = HUMAN_GUIDES[emp.department] || HUMAN_GUIDES.CRM;
              const isSelected = selectedId === emp.id;
              const empTasks = tasks.filter((t) => t.employee_id === emp.id);
              const isRunning = empTasks.some((t) => t.status === 'running');
              const waitingCount = empTasks.filter((t) => t.status === 'waiting_approval').length;

              return (
                <button
                  key={emp.id}
                  type="button"
                  onClick={() => setSelectedId(emp.id)}
                  className={`w-full text-left p-3.5 rounded-2xl border transition cursor-pointer relative overflow-hidden ${
                    isSelected
                      ? 'bg-gradient-to-r from-indigo-600/20 via-indigo-950/30 to-transparent border-indigo-500/60 shadow-lg shadow-indigo-500/10'
                      : 'bg-white/[0.02] hover:bg-white/[0.05] border-white/[0.07]'
                  }`}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-xl bg-white/[0.05] border border-white/[0.1] flex items-center justify-center text-xl shrink-0">
                        {emp.avatar_emoji || '🤖'}
                      </div>
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="text-xs font-extrabold text-white">{emp.name}</span>
                          <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border ${empGuide.tagColor}`}>
                            {empGuide.shortTag}
                          </span>
                        </div>
                        <p className="text-[11px] text-zinc-400 mt-1 leading-snug line-clamp-2">
                          {empGuide.whatIDo}
                        </p>
                      </div>
                    </div>

                    {/* Live Badge if working or waiting approval */}
                    <div className="shrink-0">
                      {isRunning ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30 animate-pulse">
                          <Loader2 className="w-3 h-3 animate-spin" /> Working
                        </span>
                      ) : waitingCount > 0 ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/40">
                          {waitingCount} Sign-Off
                        </span>
                      ) : null}
                    </div>
                  </div>
                </button>
              );
            })}
          </div>
        </div>

        {/* ==================== RIGHT COLUMN: UNIFIED WORKSPACE (OPTION A + C) ==================== */}
        <div className="lg:col-span-8 space-y-5">
          
          {/* 1. AGENT ROLE HEADER & PLAIN-ENGLISH CHEAT SHEET */}
          {activeEmployee && (
            <div className="rounded-3xl border border-white/[0.08] bg-[#0b0f1a]/90 p-5 space-y-4 shadow-xl">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-3 border-b border-white/[0.06]">
                <div className="flex items-center gap-3.5">
                  <div className="w-12 h-12 rounded-2xl bg-white/[0.06] border border-white/[0.12] flex items-center justify-center text-2xl shrink-0">
                    {selectedId === 'auto' ? '✨' : activeEmployee.avatar_emoji || '🤖'}
                  </div>
                  <div>
                    <div className="flex items-center gap-2 flex-wrap">
                      <h1 className="text-lg font-black text-white tracking-tight">
                        {selectedId === 'auto' ? 'Smart Auto-Router' : activeEmployee.name}
                      </h1>
                      <span className={`text-[10px] font-bold px-2.5 py-0.5 rounded-md border ${guide.tagColor}`}>
                        {selectedId === 'auto' ? 'Automatic Delegation' : guide.shortTag}
                      </span>
                    </div>
                    <p className="text-xs text-zinc-300 mt-0.5">
                      {selectedId === 'auto'
                        ? 'Describe what you need in plain English — we will route it to Maya (Sales), Chloe (Content), Arjun (Hiring), or David (Finance).'
                        : guide.whatIDo}
                    </p>
                  </div>
                </div>

                {selectedId !== 'auto' && (
                  <button
                    type="button"
                    onClick={() => setIsBrainDrawerOpen(!isBrainDrawerOpen)}
                    className="flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold text-zinc-300 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] transition cursor-pointer shrink-0 self-start sm:self-auto"
                  >
                    <Settings2 className="w-3.5 h-3.5 text-indigo-400" />
                    <span>{isBrainDrawerOpen ? 'Hide Brain & Rules' : 'Agent Brain & Rules'}</span>
                  </button>
                )}
              </div>

              {/* Plain-English Tools & Safety Bar */}
              {selectedId !== 'auto' && (
                <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-zinc-400 bg-white/[0.02] px-3.5 py-2.5 rounded-2xl border border-white/[0.05]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-zinc-500 font-semibold uppercase tracking-wider text-[10px]">Capabilities:</span>
                    {guide.toolsSummary.map((t, i) => (
                      <span key={i} className="px-2 py-0.5 rounded-md bg-white/[0.04] border border-white/[0.06] text-zinc-200 font-medium">
                        {t}
                      </span>
                    ))}
                  </div>
                  <div className="flex items-center gap-1.5 text-emerald-400 font-medium">
                    <ShieldCheck className="w-3.5 h-3.5 shrink-0" />
                    <span>{guide.safetyNote}</span>
                  </div>
                </div>
              )}

              {/* Optional Expandable Agent Brain, SOPs & Memory Drawer */}
              {isBrainDrawerOpen && selectedId !== 'auto' && (
                <div className="pt-3 border-t border-white/[0.08] space-y-4 animate-in fade-in duration-200">
                  <div className="bg-black/40 rounded-2xl p-4 border border-white/[0.06] space-y-2">
                    <div className="text-xs font-bold text-indigo-300 uppercase tracking-wider">
                      Standard Operating Procedures ({activeEmployee.sops?.length || 0})
                    </div>
                    <div className="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                      {activeEmployee.sops?.map((sop, idx) => (
                        <div key={idx} className="text-xs text-zinc-300 bg-white/[0.02] border border-white/[0.04] rounded-lg p-2">
                          {sop}
                        </div>
                      ))}
                    </div>
                  </div>
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <MemoryVault employeeId={activeEmployee.id} apiBase={apiBase} />
                    <PermissionPanel
                      employeeId={activeEmployee.id}
                      apiBase={apiBase}
                      employeeTools={activeEmployee.tools || []}
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 2. STEP 2 — TASK INPUT CONSOLE (OPTION C GUIDED BUILDER + OPTION A FREEFORM) */}
          <div className="rounded-3xl border border-indigo-500/30 bg-gradient-to-b from-[#0e1322] to-[#0a0e19] p-5 sm:p-6 space-y-4 shadow-2xl">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
              <div>
                <span className="text-[10px] font-extrabold uppercase tracking-wider text-indigo-400 block">
                  Step 2 • Assign Work
                </span>
                <h3 className="text-sm font-black text-white">
                  What Do You Want {selectedId === 'auto' ? 'Your AI Team' : activeEmployee?.name} To Do?
                </h3>
              </div>

              {/* Mode Switcher: Option C (Guided Recipe) vs Option A (Freeform Prompt) */}
              <div className="flex items-center bg-black/40 p-1 rounded-xl border border-white/[0.08] self-start sm:self-auto">
                <button
                  type="button"
                  onClick={() => setPromptMode('guided')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
                    promptMode === 'guided'
                      ? 'bg-indigo-600 text-white shadow'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  <Sliders className="w-3.5 h-3.5" />
                  <span>Guided Builder (Fill Blanks)</span>
                </button>
                <button
                  type="button"
                  onClick={() => setPromptMode('freeform')}
                  className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold transition cursor-pointer ${
                    promptMode === 'freeform'
                      ? 'bg-indigo-600 text-white shadow'
                      : 'text-zinc-400 hover:text-white'
                  }`}
                >
                  <MessageSquare className="w-3.5 h-3.5" />
                  <span>Freeform Prompt</span>
                </button>
              </div>
            </div>

            {/* ==================== MODE 1: OPTION C — GUIDED RECIPE BUILDER ==================== */}
            {promptMode === 'guided' ? (
              <div className="space-y-4">
                {/* CRM / Sales Guided Fields (Maya) */}
                {(activeEmployee?.department === 'CRM' || selectedId === 'auto') && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        1. Target Niche / Industry
                      </label>
                      <input
                        type="text"
                        value={crmNiche}
                        onChange={(e) => setCrmNiche(e.target.value)}
                        placeholder="e.g. Indian D2C Skincare"
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      />
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        2. Website Platform
                      </label>
                      <select
                        value={crmPlatform}
                        onChange={(e) => setCrmPlatform(e.target.value)}
                        className="w-full rounded-xl bg-[#0b0f1a] border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value="Shopify">Shopify (Verify Live Storefront)</option>
                        <option value="WooCommerce / WordPress">WooCommerce / WordPress</option>
                        <option value="Any Ecommerce Platform">Any Ecommerce Platform</option>
                      </select>
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        3. App / Tech Signals
                      </label>
                      <input
                        type="text"
                        value={crmSignals}
                        onChange={(e) => setCrmSignals(e.target.value)}
                        placeholder="e.g. Wati, Loox, Nudgify"
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      />
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        4. Target Size / Turnover Profile
                      </label>
                      <input
                        type="text"
                        value={crmRevenue}
                        onChange={(e) => setCrmRevenue(e.target.value)}
                        placeholder="e.g. ₹10L–₹50L annual profile"
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      />
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        5. Number of Prospects
                      </label>
                      <select
                        value={crmCount}
                        onChange={(e) => setCrmCount(e.target.value)}
                        className="w-full rounded-xl bg-[#0b0f1a] border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value="3">3 Verified Prospects (Fastest)</option>
                        <option value="5">5 Verified Prospects (Recommended)</option>
                        <option value="10">Up to 10 Prospects</option>
                      </select>
                    </div>

                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        6. Next Action
                      </label>
                      <select
                        value={crmGoal}
                        onChange={(e) => setCrmGoal(e.target.value)}
                        className="w-full rounded-xl bg-[#0b0f1a] border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      >
                        <option value="Verify live websites and draft cold outreach email">Verify Sites + Draft Outreach Email</option>
                        <option value="Produce a verified qualification table only (no emails)">Verified Research Table Only</option>
                      </select>
                    </div>
                  </div>
                )}

                {/* Marketing Guided Fields (Chloe) */}
                {activeEmployee?.department === 'Marketing' && selectedId !== 'auto' && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div className="sm:col-span-3">
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        1. Topic or Angle
                      </label>
                      <input
                        type="text"
                        value={mktTopic}
                        onChange={(e) => setMktTopic(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white focus:outline-none focus:border-indigo-500"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        2. Deliverable Format
                      </label>
                      <select
                        value={mktFormat}
                        onChange={(e) => setMktFormat(e.target.value)}
                        className="w-full rounded-xl bg-[#0b0f1a] border border-white/[0.1] px-3 py-2 text-xs text-white"
                      >
                        <option value="3 LinkedIn Hooks + 1 Full Founder Post">3 LinkedIn Hooks + Full Post</option>
                        <option value="5-Part Twitter / X Thread">5-Part Twitter / X Thread</option>
                        <option value="Competitor Content Teardown Report">Competitor Content Teardown</option>
                      </select>
                    </div>
                    <div className="sm:col-span-2">
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        3. Voice & Tone
                      </label>
                      <input
                        type="text"
                        value={mktTone}
                        onChange={(e) => setMktTone(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white"
                      />
                    </div>
                  </div>
                )}

                {/* HRM Guided Fields (Arjun) */}
                {activeEmployee?.department === 'HRM' && selectedId !== 'auto' && (
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        1. Role / Skillset
                      </label>
                      <input
                        type="text"
                        value={hrRole}
                        onChange={(e) => setHrRole(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        2. Target Geography
                      </label>
                      <input
                        type="text"
                        value={hrMarket}
                        onChange={(e) => setHrMarket(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        3. Hiring Objective
                      </label>
                      <input
                        type="text"
                        value={hrGoal}
                        onChange={(e) => setHrGoal(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white"
                      />
                    </div>
                  </div>
                )}

                {/* Operations Guided Fields (David) */}
                {activeEmployee?.department === 'Operations' && selectedId !== 'auto' && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        1. Finance / Audit Task
                      </label>
                      <input
                        type="text"
                        value={opsTask}
                        onChange={(e) => setOpsTask(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white"
                      />
                    </div>
                    <div>
                      <label className="text-[11px] font-semibold text-zinc-300 block mb-1">
                        2. Specific Rules or Numbers to Check
                      </label>
                      <input
                        type="text"
                        value={opsDetails}
                        onChange={(e) => setOpsDetails(e.target.value)}
                        className="w-full rounded-xl bg-black/40 border border-white/[0.1] px-3 py-2 text-xs text-white"
                      />
                    </div>
                  </div>
                )}

                {/* Auto-Assembled Prompt Preview + Launch Button */}
                <div className="rounded-2xl bg-black/50 border border-white/[0.08] p-3.5 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                  <div className="space-y-0.5 flex-1">
                    <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-400 block">
                      Auto-Built Prompt Preview
                    </span>
                    <p className="text-xs text-zinc-200 italic leading-relaxed">
                      &ldquo;{buildGuidedPrompt()}&rdquo;
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleRunTask(buildGuidedPrompt())}
                    disabled={Boolean(dispatchingId)}
                    className="flex items-center justify-center gap-2 px-5 py-3 rounded-xl text-xs font-extrabold text-white bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 shadow-lg shadow-indigo-600/30 transition cursor-pointer disabled:opacity-50 shrink-0"
                  >
                    {dispatchingId ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Running...</span>
                      </>
                    ) : (
                      <>
                        <Sparkles className="w-4 h-4" />
                        <span>Launch {selectedId === 'auto' ? 'Task' : activeEmployee?.name.split(' ')[0]} &rarr;</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            ) : (
              /* ==================== MODE 2: OPTION A — FREEFORM PROMPT ==================== */
              <div className="space-y-3">
                {/* 1-Click Starter Templates */}
                <div>
                  <span className="text-[10px] font-bold uppercase tracking-wider text-zinc-400 block mb-1.5">
                    1-Click Starter Prompts (Click to fill):
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {guide.quickChips.map((chip, idx) => (
                      <button
                        key={idx}
                        type="button"
                        onClick={() => setFreeformPrompt(chip)}
                        className="text-left text-[11px] px-3 py-1.5 rounded-xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-300 hover:text-white transition cursor-pointer"
                      >
                        ⚡ {chip}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="flex flex-col sm:flex-row gap-2.5">
                  <textarea
                    value={freeformPrompt}
                    onChange={(e) => setFreeformPrompt(e.target.value)}
                    placeholder={`Type any instruction for ${
                      selectedId === 'auto' ? 'your AI team' : activeEmployee?.name
                    }... (e.g. "Find 5 Shopify D2C jewelry stores in India and draft cold emails")`}
                    rows={3}
                    className="flex-1 rounded-2xl bg-black/50 border border-white/[0.12] p-3.5 text-xs text-white placeholder-zinc-500 focus:outline-none focus:border-indigo-500 resize-none"
                  />
                  <button
                    type="button"
                    onClick={() => handleRunTask()}
                    disabled={Boolean(dispatchingId) || !freeformPrompt.trim()}
                    className="sm:self-end flex items-center justify-center gap-2 px-6 py-3.5 rounded-2xl text-xs font-extrabold text-white bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 shadow-lg shadow-indigo-600/30 transition cursor-pointer disabled:opacity-50 shrink-0"
                  >
                    {dispatchingId ? (
                      <>
                        <Loader2 className="w-4 h-4 animate-spin" />
                        <span>Running...</span>
                      </>
                    ) : (
                      <>
                        <Send className="w-4 h-4" />
                        <span>Run Task</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            )}
          </div>

          {/* 3. INLINE PENDING APPROVALS (IF ANY EMAIL / ACTION NEEDS SIGN-OFF) */}
          {pendingApprovals.length > 0 && (
            <div className="space-y-3">
              {pendingApprovals.map((task) => (
                <div
                  key={task.id}
                  className="rounded-3xl border-2 border-amber-500/50 bg-gradient-to-b from-amber-950/25 via-[#0e111a] to-[#090c14] p-5 space-y-4 shadow-2xl"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                    <div className="flex items-center gap-2.5">
                      <span className="w-2.5 h-2.5 rounded-full bg-amber-400 animate-ping" />
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="text-sm font-black text-white">{task.employee_name}</span>
                          <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 uppercase">
                            Needs Your Approval
                          </span>
                        </div>
                        <p className="text-xs text-zinc-400">
                          Ready to send email via <code className="text-zinc-200">{activeEmailSender}</code>
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() =>
                          setShowRejectInput((prev) => ({ ...prev, [task.id]: !prev[task.id] }))
                        }
                        className="flex items-center gap-1.5 px-3.5 py-2 rounded-xl text-xs font-semibold text-zinc-300 hover:text-rose-300 bg-white/[0.05] hover:bg-rose-950/40 border border-white/[0.1] transition cursor-pointer"
                      >
                        <X className="w-3.5 h-3.5" />
                        <span>Reject / Teach Rule</span>
                      </button>
                      <button
                        type="button"
                        onClick={() => onApprove(task.id, true)}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-extrabold text-white bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-600/30 transition cursor-pointer"
                      >
                        <Mail className="w-3.5 h-3.5" />
                        <span>Approve &amp; Send Email</span>
                      </button>
                    </div>
                  </div>

                  {/* Email Preview */}
                  {task.pending_action && (
                    <div className="rounded-2xl bg-black/60 border border-amber-500/20 p-4 space-y-2 text-xs">
                      <div className="flex flex-wrap items-center justify-between gap-2 text-zinc-400 border-b border-white/[0.06] pb-2">
                        <div>
                          <span className="text-zinc-500">To: </span>
                          <strong className="text-white font-mono">
                            {String(task.pending_action.tool_params?.to || '')}
                          </strong>
                        </div>
                        <div>
                          <span className="text-zinc-500">Subject: </span>
                          <strong className="text-white">
                            {String(task.pending_action.tool_params?.subject || '')}
                          </strong>
                        </div>
                      </div>
                      <div className="text-zinc-200 whitespace-pre-wrap leading-relaxed pt-1 font-sans">
                        {String(task.pending_action.tool_params?.body || '')}
                      </div>
                    </div>
                  )}

                  {/* Optional Rejection Feedback Box */}
                  {showRejectInput[task.id] && (
                    <div className="flex gap-2 pt-1">
                      <input
                        type="text"
                        value={rejectionFeedback[task.id] || ''}
                        onChange={(e) =>
                          setRejectionFeedback((prev) => ({ ...prev, [task.id]: e.target.value }))
                        }
                        placeholder="Why are you rejecting this? (e.g. 'Never pitch unverified speed metrics')"
                        className="flex-1 rounded-xl bg-black/60 border border-rose-500/40 px-3 py-2 text-xs text-white"
                      />
                      <button
                        type="button"
                        onClick={() => {
                          onApprove(
                            task.id,
                            false,
                            rejectionFeedback[task.id] || 'Rejected by founder'
                          );
                          setShowRejectInput((prev) => ({ ...prev, [task.id]: false }));
                        }}
                        className="px-4 py-2 rounded-xl text-xs font-bold bg-rose-600 text-white cursor-pointer"
                      >
                        Confirm Reject
                      </button>
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}

          {/* 4. STEP 3 — LIVE OUTPUT & DELIVERABLE SCREEN */}
          <div className="rounded-3xl border border-white/[0.08] bg-[#0b0f1a]/90 shadow-2xl overflow-hidden">
            <div className="p-4 sm:p-5 border-b border-white/[0.06] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400">
                  <FileText className="w-4 h-4" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-sm font-black text-white">Step 3 • Live Output &amp; Deliverable</h3>
                    {activeTask?.status === 'running' && (
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30 animate-pulse">
                        <Loader2 className="w-3 h-3 animate-spin" /> Working...
                      </span>
                    )}
                    {activeTask?.status === 'completed' && (
                      <span className="flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                        <CheckCircle2 className="w-3 h-3" /> Verified Output
                      </span>
                    )}
                  </div>
                  {activeTask && (
                    <p className="text-[11px] text-zinc-400 line-clamp-1 mt-0.5">
                      Task: <span className="text-zinc-200">&ldquo;{activeTask.task_prompt}&rdquo;</span>
                    </p>
                  )}
                </div>
              </div>

              {activeTask && (
                <div className="flex items-center gap-2">
                  <div className="flex items-center bg-white/[0.04] p-1 rounded-xl border border-white/[0.08]">
                    <button
                      type="button"
                      onClick={() => setOutputTab('deliverable')}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                        outputTab === 'deliverable'
                          ? 'bg-indigo-600 text-white'
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      Deliverable
                    </button>
                    <button
                      type="button"
                      onClick={() => setOutputTab('steps')}
                      className={`px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                        outputTab === 'steps'
                          ? 'bg-indigo-600 text-white'
                          : 'text-zinc-400 hover:text-white'
                      }`}
                    >
                      Steps ({activeTask.steps?.length || 0})
                    </button>
                  </div>

                  {activeTask.final_output && (
                    <button
                      type="button"
                      onClick={handleCopyOutput}
                      className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-zinc-200 bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] cursor-pointer"
                    >
                      {copied ? (
                        <>
                          <Check className="w-3.5 h-3.5 text-emerald-400" />
                          <span className="text-emerald-400">Copied</span>
                        </>
                      ) : (
                        <>
                          <Copy className="w-3.5 h-3.5" />
                          <span>Copy</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Recent Task Switcher Bar */}
            {visibleTasks.length > 1 && (
              <div className="px-5 py-2 border-b border-white/[0.04] bg-black/30 flex items-center gap-2 overflow-x-auto">
                <span className="text-[10px] text-zinc-500 uppercase font-bold shrink-0">History:</span>
                {visibleTasks.slice(0, 6).map((t, idx) => (
                  <button
                    key={t.id}
                    type="button"
                    onClick={() => setSelectedTaskId(t.id)}
                    className={`text-[11px] px-2.5 py-1 rounded-lg font-mono transition shrink-0 cursor-pointer ${
                      activeTask?.id === t.id
                        ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 font-bold'
                        : 'text-zinc-400 hover:text-zinc-200 bg-white/[0.02] border border-white/[0.04]'
                    }`}
                  >
                    {idx === 0 ? 'Latest' : `Run #${visibleTasks.length - idx}`} ({t.status})
                  </button>
                ))}
              </div>
            )}

            {/* Deliverable or Live Steps Content */}
            <div className="p-5 sm:p-6 min-h-[260px] max-h-[600px] overflow-y-auto">
              {!activeTask ? (
                <div className="py-12 text-center space-y-2">
                  <div className="text-3xl">🚀</div>
                  <div className="text-sm font-bold text-white">Ready to Run Your First Task</div>
                  <p className="text-xs text-zinc-400 max-w-md mx-auto">
                    Fill in the blanks in the Guided Builder above or click a 1-Click Starter Prompt to watch {activeEmployee?.name || 'your agent'} work live.
                  </p>
                </div>
              ) : outputTab === 'deliverable' ? (
                activeTask.status === 'running' ? (
                  <div className="py-12 text-center space-y-4">
                    <Loader2 className="w-8 h-8 text-indigo-400 animate-spin mx-auto" />
                    <div className="space-y-1">
                      <h4 className="text-sm font-bold text-white">
                        {activeTask.employee_name} is Researching &amp; Verifying...
                      </h4>
                      <p className="text-xs text-zinc-400 max-w-md mx-auto">
                        Executing multi-hop search, checking live domain footprints, and validating evidence.
                      </p>
                    </div>
                    {activeTask.steps?.length > 0 && (
                      <div className="max-w-lg mx-auto text-left bg-black/40 border border-white/[0.06] rounded-2xl p-3.5 space-y-1.5">
                        <div className="text-[10px] font-bold uppercase text-indigo-400">
                          Latest Completed Step ({activeTask.steps.length}):
                        </div>
                        <div className="text-xs text-zinc-300">
                          {activeTask.steps[activeTask.steps.length - 1].thought}
                        </div>
                      </div>
                    )}
                  </div>
                ) : activeTask.final_output ? (
                  <div className="bg-[#07090f] rounded-2xl border border-white/[0.06] p-5 sm:p-6">
                    <MarkdownViewer content={activeTask.final_output} />
                  </div>
                ) : (
                  <div className="py-10 text-center text-zinc-400 text-xs">
                    Task status: <strong className="text-white">{activeTask.status}</strong>. Switch to the &ldquo;Steps&rdquo; tab to inspect tool logs.
                  </div>
                )
              ) : (
                <ExecutionMonitor task={activeTask} auditLog={auditLog} />
              )}
            </div>

            {/* Footer Telemetry */}
            {activeTask && (
              <div className="px-5 py-3 border-t border-white/[0.06] bg-black/40 flex flex-wrap items-center justify-between gap-3 text-[11px] text-zinc-400">
                <div className="flex items-center gap-4">
                  <span className="flex items-center gap-1 font-mono text-zinc-300">
                    <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
                    Cost: ${(activeTask.cost_usd || 0.0004).toFixed(4)}
                  </span>
                  <span className="flex items-center gap-1 font-mono text-zinc-300">
                    <Zap className="w-3.5 h-3.5 text-purple-400" />
                    Tokens: {(activeTask.tokens_used || 0).toLocaleString()}
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="w-3.5 h-3.5 text-amber-400" />
                    Saved: ~{activeTask.time_saved_mins || 20}m
                  </span>
                </div>
                <div className="text-[10px] text-zinc-500 font-mono">
                  {new Date(activeTask.created_at).toLocaleTimeString()}
                </div>
              </div>
            )}
          </div>

        </div>

      </div>
    </div>
  );
}
