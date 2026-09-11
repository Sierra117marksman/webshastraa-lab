'use client';

import React, { useState } from 'react';
import {
  AlertTriangle,
  X,
  Mail,
  ShieldCheck,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { TaskRecord } from '@/types';

interface ApprovalFeedProps {
  tasks: TaskRecord[];
  onApprove: (taskId: string, approved: boolean) => Promise<void>;
  activeEmailSender: string;
}

export default function ApprovalFeed({
  tasks,
  onApprove,
  activeEmailSender
}: ApprovalFeedProps) {
  const [expandedTasks, setExpandedTasks] = useState<{ [id: string]: boolean }>({});

  const toggleTask = (id: string) => {
    setExpandedTasks((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const pendingApprovals = tasks.filter((t) => t.status === 'waiting_approval');
  const pastTasks = tasks.filter((t) => t.status !== 'waiting_approval');

  return (
    <div id="tour-approvals" className="space-y-8 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between border-b border-white/[0.08] pb-5">
        <div>
          <h2 className="text-2xl font-black text-white tracking-tight">Execution & Approvals</h2>
          <p className="text-xs text-zinc-400 mt-1">
            Real-time audit trail and human-in-the-loop authorization queue
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="text-zinc-400">Live Agent Stream</span>
        </div>
      </div>

      {/* PENDING APPROVALS QUEUE */}
      {pendingApprovals.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-amber-400">
            <AlertTriangle className="w-4 h-4 animate-bounce" />
            <h3 className="text-xs font-bold uppercase tracking-wider">
              Urgent: Sign-Off Required ({pendingApprovals.length})
            </h3>
          </div>

          <div className="space-y-4">
            {pendingApprovals.map((task) => (
              <div
                key={task.id}
                className="rounded-3xl border-2 border-amber-500/40 bg-gradient-to-b from-amber-950/20 via-[#0e111a] to-[#07090e] p-6 space-y-5 shadow-2xl shadow-amber-950/20 ring-1 ring-amber-500/20"
              >
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2">
                      <h4 className="font-extrabold text-white text-base">{task.employee_name}</h4>
                      <span className="text-[10px] font-bold px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 border border-amber-500/40 uppercase tracking-wider">
                        Action Hold
                      </span>
                    </div>
                    <p className="text-xs text-zinc-300 mt-1">
                      Assigned Mission: &quot;{task.task_prompt}&quot;
                    </p>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => onApprove(task.id, false)}
                      className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:text-rose-300 bg-white/[0.04] hover:bg-rose-950/30 border border-white/[0.08] hover:border-rose-500/30 transition cursor-pointer"
                    >
                      <X className="w-3.5 h-3.5" />
                      <span>Reject</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => onApprove(task.id, true)}
                      className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-600/25 transition active:scale-95 cursor-pointer"
                    >
                      <Mail className="w-3.5 h-3.5" />
                      <span>Authorize & Send via Gmail</span>
                    </button>
                  </div>
                </div>

                {/* Email Dispatch Preview Box */}
                {task.pending_action && (
                  <div className="rounded-2xl bg-black/60 border border-amber-500/20 p-4 space-y-3 text-xs">
                    <div className="flex items-center justify-between text-amber-300 font-semibold border-b border-white/[0.06] pb-2">
                      <span className="flex items-center gap-1.5">
                        <ShieldCheck className="w-4 h-4 text-amber-400" />
                        <span>Proposed Action: {task.pending_action.tool_name}</span>
                      </span>
                      <span className="text-[11px] text-zinc-400 font-mono">
                        via {activeEmailSender} (Port 465 SSL)
                      </span>
                    </div>

                    <div className="text-zinc-300 text-[11px]">
                      <span className="text-zinc-500 font-medium">Internal SOP Rationale: </span>
                      {task.pending_action.explanation}
                    </div>

                    {/* Email Card Preview */}
                    <div className="rounded-xl bg-[#080b12] p-4 border border-white/[0.08] space-y-2 font-mono text-[11px]">
                      <div className="flex items-center gap-2 text-zinc-400">
                        <span className="w-16 text-zinc-500">To:</span>
                        <span className="text-zinc-200 font-semibold">{String(task.pending_action.tool_params?.to || 'recipient@domain.com')}</span>
                      </div>
                      <div className="flex items-center gap-2 text-zinc-400">
                        <span className="w-16 text-zinc-500">Subject:</span>
                        <span className="text-zinc-200 font-semibold">{String(task.pending_action.tool_params?.subject || 'Executive Inquiry')}</span>
                      </div>
                      <div className="pt-3 border-t border-white/[0.06] font-sans text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
                        {String(task.pending_action.tool_params?.body || '')}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* HISTORICAL EXECUTION LOG */}
      <div className="space-y-4">
        <h3 className="text-xs font-bold uppercase tracking-wider text-zinc-400">
          Activity Timeline ({pastTasks.length})
        </h3>

        {pastTasks.length === 0 ? (
          <div className="text-center py-16 border border-dashed border-white/[0.08] rounded-2xl text-zinc-500 text-xs">
            No past executions recorded yet. Run a mission from the Workforce Roster.
          </div>
        ) : (
          <div className="space-y-3.5">
            {pastTasks.map((task) => {
              const isExpanded = expandedTasks[task.id] || false;
              return (
                <div
                  key={task.id}
                  className="rounded-2xl border border-white/[0.06] bg-[#0a0d14]/80 p-5 space-y-3 hover:border-white/[0.12] transition"
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-bold text-white text-sm">{task.employee_name}</span>
                        <span
                          className={`text-[9px] font-bold px-2 py-0.5 rounded-full uppercase tracking-wider ${
                            task.status === 'completed'
                              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                              : task.status === 'rejected'
                              ? 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                              : 'bg-white/[0.06] text-zinc-400'
                          }`}
                        >
                          {task.status}
                        </span>
                      </div>
                      <p className="text-xs text-zinc-400 mt-0.5">{task.task_prompt}</p>
                    </div>

                    <div className="flex items-center gap-3">
                      <span suppressHydrationWarning className="text-[10px] text-zinc-500 font-mono">
                        {new Date(task.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                      </span>
                      <button
                        type="button"
                        onClick={() => toggleTask(task.id)}
                        className="p-1 rounded text-zinc-500 hover:text-zinc-300 transition cursor-pointer"
                      >
                        {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
                      </button>
                    </div>
                  </div>

                  {/* Step Breakdown */}
                  {task.steps.length > 0 && (
                    <div className="space-y-1.5 pt-1">
                      {task.steps.map((s, idx) => (
                        <div
                          key={idx}
                          className="rounded-xl bg-black/40 border border-white/[0.04] p-3 text-xs space-y-1"
                        >
                          <div className="text-indigo-300 font-medium flex items-center gap-2">
                            <span className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-500/10 border border-indigo-500/20">
                              Step {s.step_number}
                            </span>
                            <span>{s.thought}</span>
                          </div>
                          {s.tool_called && (
                            <div className="text-[11px] text-zinc-400 flex items-center gap-1.5 font-mono pt-1">
                              <span className="text-zinc-500">Tool:</span>
                              <span className="text-zinc-200">{s.tool_called}</span>
                            </div>
                          )}
                        </div>
                      ))}
                    </div>
                  )}

                  {/* Expandable Deliverable */}
                  {task.final_output && (
                    <div className="rounded-xl bg-black/60 border border-white/[0.06] p-4 text-xs space-y-2">
                      <div className="font-bold text-zinc-500 text-[10px] uppercase tracking-wider">
                        Executive Deliverable Output
                      </div>
                      <div className="whitespace-pre-wrap leading-relaxed text-zinc-300 font-sans text-xs">
                        {task.final_output}
                      </div>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
