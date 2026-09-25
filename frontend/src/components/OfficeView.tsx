'use client';

import React, { useState, useEffect } from 'react';
import {
  ArrowLeft,
  Send,
  Check,
  X,
  Shield,
  Activity,
  Sparkles,
  Clock,
  Terminal,
  AlertCircle,
  CheckCircle2,
  Inbox,
  Loader2
} from 'lucide-react';
import { AIEmployeeSpec, TaskRecord, AuditLogEntry } from '@/types';
import ExecutionMonitor from './ExecutionMonitor';
import MemoryVault from './MemoryVault';
import PermissionPanel from './PermissionPanel';

interface OfficeViewProps {
  employee: AIEmployeeSpec;
  tasks: TaskRecord[];
  apiBase: string;
  onDispatch: (id: string, prompt?: string) => void;
  onApprove: (taskId: string, approved: boolean, feedback?: string) => void;
  onClose: () => void;
}

const QUICK_MISSIONS: Record<string, string[]> = {
  CRM: [
    'Research top 10 leads in enterprise B2B SaaS',
    'Draft cold outreach sequence for warm prospects',
    'Audit CRM contacts and flag accounts without phone numbers'
  ],
  HRM: [
    'Screen latest applicants against role scorecard',
    'Draft interview invitations for top shortlisted candidates',
    'Compile weekly recruitment funnel telemetry'
  ],
  Marketing: [
    'Find 5 trending topics in agentic AI and LLM workflows',
    'Draft 3 LinkedIn hooks with distinct storytelling angles',
    'Analyze competitor market announcements and extract founder takeaways'
  ],
  Operations: [
    'Audit submitted vendor invoices for mathematical errors',
    'Reconcile contractor billable hours against monthly caps',
    'Flag suspicious billing anomalies and draft inquiry notices'
  ]
};

const THEME_STYLES: Record<string, { bg: string; border: string; text: string; glow: string; badge: string }> = {
  indigo: { bg: 'bg-indigo-500/10', border: 'border-indigo-500/30', text: 'text-indigo-400', glow: 'shadow-indigo-500/20', badge: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30' },
  violet: { bg: 'bg-violet-500/10', border: 'border-violet-500/30', text: 'text-violet-400', glow: 'shadow-violet-500/20', badge: 'bg-violet-500/20 text-violet-300 border-violet-500/30' },
  rose: { bg: 'bg-rose-500/10', border: 'border-rose-500/30', text: 'text-rose-400', glow: 'shadow-rose-500/20', badge: 'bg-rose-500/20 text-rose-300 border-rose-500/30' },
  amber: { bg: 'bg-amber-500/10', border: 'border-amber-500/30', text: 'text-amber-400', glow: 'shadow-amber-500/20', badge: 'bg-amber-500/20 text-amber-300 border-amber-500/30' },
  emerald: { bg: 'bg-emerald-500/10', border: 'border-emerald-500/30', text: 'text-emerald-400', glow: 'shadow-emerald-500/20', badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
  sky: { bg: 'bg-sky-500/10', border: 'border-sky-500/30', text: 'text-sky-400', glow: 'shadow-sky-500/20', badge: 'bg-sky-500/20 text-sky-300 border-sky-500/30' }
};

export default function OfficeView({
  employee,
  tasks,
  apiBase,
  onDispatch,
  onApprove,
  onClose
}: OfficeViewProps) {
  const [customPrompt, setCustomPrompt] = useState('');
  const [isDispatching, setIsDispatching] = useState(false);
  const [rejectionFeedback, setRejectionFeedback] = useState<Record<string, string>>({});
  const [auditLog, setAuditLog] = useState<AuditLogEntry[]>([]);

  const theme = THEME_STYLES[employee.theme_color] || THEME_STYLES.indigo;

  // Filter tasks specific to this employee
  const employeeTasks = tasks.filter((t) => t.employee_id === employee.id);
  const latestTask = employeeTasks[0];
  const pendingApprovals = employeeTasks.filter((t) => t.status === 'waiting_approval');

  // Status computation
  const isRunning = employeeTasks.some((t) => t.status === 'running');
  const hasPendingApproval = pendingApprovals.length > 0;
  const statusLabel = isRunning ? 'Executing Task' : hasPendingApproval ? 'Needs Founder Sign-Off' : 'At Executive Desk';
  const statusColor = isRunning ? 'bg-sky-400' : hasPendingApproval ? 'bg-amber-400' : 'bg-emerald-400';

  // Fetch audit log for this employee
  useEffect(() => {
    let isMounted = true;
    const loadAudit = async () => {
      try {
        const res = await fetch(`${apiBase}/api/audit-log?employee_id=${employee.id}&limit=50`);
        if (res.ok) {
          const data = await res.json();
          if (isMounted) setAuditLog(data);
        }
      } catch {
        // Silently swallow transient network polling hiccups
      }
    };
    loadAudit();
    const interval = setInterval(loadAudit, 4000);
    return () => {
      isMounted = false;
      clearInterval(interval);
    };
  }, [apiBase, employee.id]);

  const handleLaunchDispatch = async (promptText?: string) => {
    const textToRun = promptText || customPrompt;
    if (!textToRun.trim()) return;
    setIsDispatching(true);
    try {
      await onDispatch(employee.id, textToRun);
      setCustomPrompt('');
    } finally {
      setIsDispatching(false);
    }
  };

  const handleRejectWithFeedback = (taskId: string) => {
    const feedback = rejectionFeedback[taskId] || 'Rejected by founder';
    onApprove(taskId, false, feedback);
    setRejectionFeedback((prev) => {
      const next = { ...prev };
      delete next[taskId];
      return next;
    });
  };

  const quickChips = QUICK_MISSIONS[employee.department] || [
    'Execute core departmental objective',
    'Review operational logs and report exceptions',
    'Formulate high-priority action plan'
  ];

  return (
    <div className="space-y-6 animate-in fade-in slide-in-from-right-4 duration-300 pb-16">
      {/* Office Header Banner */}
      <div className="relative rounded-3xl border border-white/[0.08] bg-gradient-to-br from-[#0c101c] via-[#090c15] to-[#07090f] p-6 sm:p-8 overflow-hidden shadow-2xl">
        <div className="absolute top-0 right-0 w-96 h-96 bg-gradient-to-br from-indigo-500/10 via-purple-500/5 to-transparent blur-3xl pointer-events-none -z-0" />

        <div className="relative z-10 flex flex-col md:flex-row md:items-center justify-between gap-6">
          <div className="flex items-start sm:items-center gap-4">
            <button
              type="button"
              onClick={onClose}
              className="p-2.5 rounded-2xl bg-white/[0.04] hover:bg-white/[0.08] border border-white/[0.08] text-zinc-400 hover:text-white transition cursor-pointer shrink-0 mt-1 sm:mt-0"
              aria-label="Back to Floorplan"
            >
              <ArrowLeft className="w-5 h-5" />
            </button>

            <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-white/[0.08] to-white/[0.02] border border-white/[0.12] flex items-center justify-center text-3xl shadow-inner shrink-0">
              {employee.avatar_emoji || '🤖'}
            </div>

            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <h1 className="text-2xl font-black text-white tracking-tight">{employee.name}</h1>
                <span className={`text-[10px] font-bold px-2 py-0.5 rounded-md border ${theme.badge}`}>
                  {employee.department}
                </span>
                <div className="flex items-center gap-1.5 px-2.5 py-0.5 rounded-full bg-white/[0.04] border border-white/[0.08] text-xs text-zinc-300">
                  <span className={`w-2 h-2 rounded-full ${statusColor} ${isRunning ? 'animate-pulse' : ''}`} />
                  <span className="text-[11px] font-medium">{statusLabel}</span>
                </div>
              </div>
              <p className="text-xs text-zinc-400 font-medium mt-1">{employee.role}</p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="px-3.5 py-2 rounded-xl bg-white/[0.03] border border-white/[0.06] text-right">
              <span className="text-[10px] text-zinc-500 uppercase tracking-wider block">Office Status</span>
              <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5 justify-end">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" /> Online & Governed
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* 2-Column Office Floorplan Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        {/* LEFT COLUMN: Executive Desk + Execution Monitor + Memory Vault */}
        <div className="space-y-6">
          {/* Zone 1: Executive Desk */}
          <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
              <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
                <span>🛋️</span> Executive Desk & Governance
              </span>
              <span className="text-[11px] text-zinc-500 font-mono">ID: {employee.id}</span>
            </div>

            <div className="space-y-3">
              <div>
                <span className="text-[11px] text-zinc-500 block uppercase tracking-wider mb-1 font-semibold">Core Objective</span>
                <p className="text-xs text-zinc-300 leading-relaxed bg-white/[0.02] p-3 rounded-xl border border-white/[0.04]">
                  {employee.objective}
                </p>
              </div>

              <div>
                <span className="text-[11px] text-zinc-500 block uppercase tracking-wider mb-1 font-semibold">Behavioral Persona</span>
                <p className="text-xs text-zinc-400 italic bg-white/[0.02] p-3 rounded-xl border border-white/[0.04]">
                  "{employee.persona}"
                </p>
              </div>

              <div>
                <span className="text-[11px] text-zinc-500 block uppercase tracking-wider mb-1.5 font-semibold">
                  Standard Operating Procedures ({employee.sops?.length || 0})
                </span>
                <div className="space-y-1.5 max-h-48 overflow-y-auto pr-1">
                  {employee.sops?.map((sop, idx) => (
                    <div key={idx} className="text-xs text-zinc-300 bg-white/[0.02] border border-white/[0.04] rounded-lg p-2 leading-relaxed">
                      {sop}
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <span className="text-[11px] text-zinc-500 block uppercase tracking-wider mb-1.5 font-semibold">Equipped Toolbelt</span>
                <div className="flex flex-wrap gap-1.5">
                  {employee.tools?.map((toolId) => (
                    <span
                      key={toolId}
                      className="px-2.5 py-1 rounded-lg text-[11px] font-mono bg-white/[0.04] border border-white/[0.08] text-zinc-300 flex items-center gap-1.5"
                    >
                      <span>⚙️</span> {toolId}
                    </span>
                  ))}
                </div>
              </div>
            </div>
          </div>

          {/* Zone 3: Execution Monitor */}
          {latestTask ? (
            <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-6 shadow-xl space-y-4">
              <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
                <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
                  <Terminal className="w-4 h-4 text-indigo-400" /> Execution Monitor
                </span>
                <span className="text-[11px] text-zinc-500 font-mono">Task: {latestTask.id}</span>
              </div>
              <ExecutionMonitor task={latestTask} auditLog={auditLog} />
            </div>
          ) : (
            <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/80 p-8 text-center space-y-2">
              <Terminal className="w-8 h-8 text-zinc-600 mx-auto" />
              <p className="text-xs text-zinc-400 font-semibold">No Tasks Executed Yet</p>
              <p className="text-[11px] text-zinc-500">Dispatch a task from the console to monitor live actions and guardrails.</p>
            </div>
          )}

          {/* Zone 5: Memory Vault */}
          <MemoryVault employeeId={employee.id} apiBase={apiBase} />
        </div>

        {/* RIGHT COLUMN: Dispatch Console + Approval In-Tray + Permission Panel */}
        <div className="space-y-6">
          {/* Zone 2: Dispatch Console */}
          <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
              <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-amber-400" /> Dispatch Mission Console
              </span>
              <span className="text-[11px] text-zinc-500 font-mono">{employeeTasks.length} Dispatched</span>
            </div>

            <div className="space-y-3">
              <div>
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-2 font-semibold">Quick Missions</span>
                <div className="flex flex-col gap-2">
                  {quickChips.map((chip, idx) => (
                    <button
                      key={idx}
                      type="button"
                      onClick={() => handleLaunchDispatch(chip)}
                      disabled={isDispatching}
                      className="text-left text-xs text-zinc-300 hover:text-white bg-white/[0.03] hover:bg-white/[0.06] border border-white/[0.06] hover:border-white/[0.12] p-2.5 rounded-xl transition flex items-center justify-between group cursor-pointer disabled:opacity-50"
                    >
                      <span>{chip}</span>
                      <Send className="w-3 h-3 text-zinc-500 group-hover:text-amber-400 transition shrink-0 ml-2" />
                    </button>
                  ))}
                </div>
              </div>

              <div className="pt-2">
                <span className="text-[10px] text-zinc-500 uppercase tracking-wider block mb-2 font-semibold">Custom Task Prompt</span>
                <textarea
                  value={customPrompt}
                  onChange={(e) => setCustomPrompt(e.target.value)}
                  placeholder={`Assign a bespoke task to ${employee.name}...`}
                  rows={3}
                  className="w-full rounded-2xl bg-white/[0.03] border border-white/[0.08] p-3 text-xs text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-indigo-500/50 transition resize-none"
                />
                <button
                  type="button"
                  onClick={() => handleLaunchDispatch()}
                  disabled={isDispatching || !customPrompt.trim()}
                  className="w-full mt-2 flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 transition shadow-lg shadow-indigo-600/30 cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {isDispatching ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Synthesizing & Dispatching...</span>
                    </>
                  ) : (
                    <>
                      <Send className="w-4 h-4" />
                      <span>Launch Mission</span>
                    </>
                  )}
                </button>
              </div>
            </div>
          </div>

          {/* Zone 4: Approval In-Tray */}
          <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between pb-3 border-b border-white/[0.06]">
              <span className="text-xs font-bold text-zinc-300 uppercase tracking-wider flex items-center gap-2">
                <Inbox className="w-4 h-4 text-rose-400" /> Approval In-Tray
              </span>
              {pendingApprovals.length > 0 && (
                <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  {pendingApprovals.length} Pending
                </span>
              )}
            </div>

            {pendingApprovals.length === 0 ? (
              <div className="p-6 text-center text-zinc-500 space-y-1">
                <CheckCircle2 className="w-6 h-6 text-emerald-400/60 mx-auto" />
                <p className="text-xs font-medium text-zinc-400">All actions cleared</p>
                <p className="text-[11px] text-zinc-600">No restricted tool dispatches are currently paused.</p>
              </div>
            ) : (
              <div className="space-y-4">
                {pendingApprovals.map((task) => (
                  <div
                    key={task.id}
                    className="rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 space-y-3"
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-amber-300 flex items-center gap-1.5">
                        <AlertCircle className="w-3.5 h-3.5" />
                        Tool: {task.pending_action?.tool_name}
                      </span>
                      <span className="text-[10px] text-zinc-500 font-mono">{task.id}</span>
                    </div>

                    <div className="bg-black/30 p-2.5 rounded-xl border border-white/[0.04] space-y-1">
                      <p className="text-[11px] text-zinc-400 font-medium">{task.pending_action?.explanation}</p>
                      {task.pending_action?.tool_params && (
                        <pre className="text-[10px] text-zinc-500 font-mono overflow-x-auto p-1 bg-white/[0.02] rounded">
                          {JSON.stringify(task.pending_action.tool_params, null, 2)}
                        </pre>
                      )}
                    </div>

                    {/* Rejection Feedback Box */}
                    <div>
                      <input
                        type="text"
                        placeholder="Reason / feedback for rejection (triggers reflection)..."
                        value={rejectionFeedback[task.id] || ''}
                        onChange={(e) =>
                          setRejectionFeedback({ ...rejectionFeedback, [task.id]: e.target.value })
                        }
                        className="w-full text-xs bg-white/[0.04] border border-white/[0.08] rounded-xl px-3 py-1.5 text-zinc-200 placeholder-zinc-600 focus:outline-none"
                      />
                    </div>

                    {/* Action Buttons */}
                    <div className="flex items-center gap-2 pt-1">
                      <button
                        type="button"
                        onClick={() => onApprove(task.id, true)}
                        className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-xl text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-500 transition cursor-pointer"
                      >
                        <Check className="w-3.5 h-3.5" /> Approve
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRejectWithFeedback(task.id)}
                        className="flex-1 flex items-center justify-center gap-1 px-3 py-1.5 rounded-xl text-xs font-bold text-rose-300 bg-rose-500/20 hover:bg-rose-500/30 border border-rose-500/30 transition cursor-pointer"
                      >
                        <X className="w-3.5 h-3.5" /> Reject
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Zone 6: Permission Panel */}
          <PermissionPanel
            employeeId={employee.id}
            apiBase={apiBase}
            employeeTools={employee.tools || []}
          />
        </div>
      </div>
    </div>
  );
}
