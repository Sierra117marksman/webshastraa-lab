'use client';

import React, { useState } from 'react';
import {
  FileText,
  Copy,
  Check,
  Terminal,
  Clock,
  DollarSign,
  Zap,
  CheckCircle2,
  AlertCircle,
  Loader2,
  ChevronDown
} from 'lucide-react';
import { TaskRecord, AuditLogEntry, AIEmployeeSpec } from '@/types';
import ExecutionMonitor from './ExecutionMonitor';

interface AgentOutputDeskProps {
  employee: AIEmployeeSpec;
  tasks: TaskRecord[];
  auditLog: AuditLogEntry[];
}

export default function AgentOutputDesk({
  employee,
  tasks,
  auditLog
}: AgentOutputDeskProps) {
  const [copied, setCopied] = useState(false);
  const [activeView, setActiveView] = useState<'deliverable' | 'execution'>('deliverable');
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);

  // Filter tasks for this employee
  const employeeTasks = tasks.filter((t) => t.employee_id === employee.id);

  // Active task is either the selected one or the latest
  const activeTask = selectedTaskId
    ? employeeTasks.find((t) => t.id === selectedTaskId) || employeeTasks[0]
    : employeeTasks[0];

  const handleCopy = () => {
    if (!activeTask?.final_output) return;
    navigator.clipboard.writeText(activeTask.final_output);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!activeTask) {
    return (
      <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-8 text-center space-y-3 shadow-xl">
        <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center mx-auto text-2xl">
          📄
        </div>
        <h3 className="text-sm font-bold text-white tracking-tight">Agent Output Screen</h3>
        <p className="text-xs text-zinc-400 max-w-sm mx-auto leading-relaxed">
          {employee.name} has no deliverables yet. Pick a Quick Mission or type a prompt in the Dispatch Console to generate live work.
        </p>
      </div>
    );
  }

  const isRunning = activeTask.status === 'running';
  const isAwaiting = activeTask.status === 'waiting_approval';
  const isFailed = activeTask.status === 'failed' || activeTask.status === 'rejected';
  const isCompleted = activeTask.status === 'completed';

  return (
    <div className="rounded-3xl border border-white/[0.08] bg-[#0c101c]/90 backdrop-blur-xl shadow-2xl overflow-hidden flex flex-col">
      {/* Top Bar: Title, Task Switcher, and Mode Toggle */}
      <div className="p-4 sm:p-5 border-b border-white/[0.06] bg-white/[0.01] flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-indigo-500/10 border border-indigo-500/30 flex items-center justify-center text-indigo-400 shrink-0">
            <FileText className="w-4 h-4" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="text-sm font-black text-white tracking-tight">Agent Output & Deliverable</h3>
              {/* Status Badge */}
              {isRunning && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30 animate-pulse">
                  <Loader2 className="w-3 h-3 animate-spin" />
                  Generating Deliverable...
                </span>
              )}
              {isAwaiting && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30">
                  <AlertCircle className="w-3 h-3" />
                  Approval Required
                </span>
              )}
              {isCompleted && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                  <CheckCircle2 className="w-3 h-3" />
                  Completed Deliverable
                </span>
              )}
              {isFailed && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-bold bg-rose-500/20 text-rose-300 border border-rose-500/30">
                  <AlertCircle className="w-3 h-3" />
                  Action Blocked / Failed
                </span>
              )}
            </div>
            <p className="text-[11px] text-zinc-400 line-clamp-1 mt-0.5">
              Mission: <span className="text-zinc-200 font-medium">&quot;{activeTask.task_prompt}&quot;</span>
            </p>
          </div>
        </div>

        {/* Action Controls */}
        <div className="flex items-center gap-2 shrink-0">
          {/* View Mode Toggle: Deliverable vs Execution Audit */}
          <div className="flex items-center bg-white/[0.04] p-1 rounded-xl border border-white/[0.08]">
            <button
              type="button"
              onClick={() => setActiveView('deliverable')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                activeView === 'deliverable'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <FileText className="w-3.5 h-3.5" />
              <span>Deliverable</span>
            </button>
            <button
              type="button"
              onClick={() => setActiveView('execution')}
              className={`flex items-center gap-1.5 px-3 py-1 rounded-lg text-xs font-semibold transition cursor-pointer ${
                activeView === 'execution'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-zinc-400 hover:text-white'
              }`}
            >
              <Terminal className="w-3.5 h-3.5" />
              <span>Execution Audit</span>
            </button>
          </div>

          {/* Copy Button (only in deliverable view) */}
          {activeView === 'deliverable' && activeTask.final_output && (
            <button
              type="button"
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-3.5 py-1.5 rounded-xl text-xs font-bold text-zinc-200 hover:text-white bg-white/[0.06] hover:bg-white/[0.1] border border-white/[0.08] transition cursor-pointer active:scale-95"
            >
              {copied ? (
                <>
                  <Check className="w-3.5 h-3.5 text-emerald-400" />
                  <span className="text-emerald-400">Copied!</span>
                </>
              ) : (
                <>
                  <Copy className="w-3.5 h-3.5" />
                  <span>Copy Work</span>
                </>
              )}
            </button>
          )}
        </div>
      </div>

      {/* Task History Tabs (if multiple tasks) */}
      {employeeTasks.length > 1 && (
        <div className="px-5 py-2 border-b border-white/[0.04] bg-black/20 flex items-center gap-2 overflow-x-auto">
          <span className="text-[10px] text-zinc-500 uppercase tracking-wider font-semibold shrink-0">
            Recent Runs:
          </span>
          {employeeTasks.slice(0, 6).map((t, idx) => {
            const isSelected = t.id === activeTask.id;
            return (
              <button
                key={t.id}
                type="button"
                onClick={() => setSelectedTaskId(t.id)}
                className={`text-[11px] px-2.5 py-1 rounded-lg font-mono transition shrink-0 cursor-pointer ${
                  isSelected
                    ? 'bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 font-bold'
                    : 'text-zinc-400 hover:text-zinc-200 bg-white/[0.02] border border-white/[0.04]'
                }`}
              >
                {idx === 0 ? 'Latest' : `Run #${employeeTasks.length - idx}`} ({t.status})
              </button>
            );
          })}
        </div>
      )}

      {/* Main Content Area */}
      <div className="p-5 sm:p-6 min-h-[320px] max-h-[580px] overflow-y-auto">
        {activeView === 'deliverable' ? (
          <div>
            {isRunning ? (
              <div className="py-16 text-center space-y-3">
                <Loader2 className="w-8 h-8 text-indigo-400 animate-spin mx-auto" />
                <h4 className="text-sm font-bold text-white">Synthesizing Deliverable</h4>
                <p className="text-xs text-zinc-400 max-w-sm mx-auto">
                  {employee.name} is executing SOPs, verifying factual primary sources, and assembling your final deliverable.
                </p>
              </div>
            ) : activeTask.final_output ? (
              <div className="bg-[#07090f] rounded-2xl border border-white/[0.06] p-5 sm:p-6 shadow-inner font-sans text-xs text-zinc-200 leading-relaxed space-y-4 whitespace-pre-wrap selection:bg-indigo-500/40">
                {activeTask.final_output}
              </div>
            ) : (
              <div className="py-12 text-center text-zinc-500 space-y-1">
                <Terminal className="w-6 h-6 mx-auto opacity-50" />
                <p className="text-xs font-semibold">No Output Generated</p>
                <p className="text-[11px]">Task status: {activeTask.status}</p>
              </div>
            )}
          </div>
        ) : (
          <ExecutionMonitor task={activeTask} auditLog={auditLog} />
        )}
      </div>

      {/* Deliverable Metadata Footer */}
      <div className="px-5 py-3 border-t border-white/[0.06] bg-black/40 flex flex-wrap items-center justify-between gap-3 text-[11px] text-zinc-400">
        <div className="flex items-center gap-4">
          <span className="flex items-center gap-1.5 font-mono text-zinc-300">
            <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
            Cost: ${(activeTask.cost_usd || 0.0004).toFixed(4)}
          </span>
          <span className="flex items-center gap-1.5 font-mono text-zinc-300">
            <Zap className="w-3.5 h-3.5 text-purple-400" />
            Tokens: {(activeTask.tokens_used || 0).toLocaleString()}
          </span>
          <span className="flex items-center gap-1.5 text-zinc-400">
            <Clock className="w-3.5 h-3.5 text-amber-400" />
            Saved: ~{activeTask.time_saved_mins || 20}m
          </span>
        </div>

        <div className="text-[10px] text-zinc-500 font-mono">
          Task ID: {activeTask.id} • {new Date(activeTask.created_at).toLocaleTimeString()}
        </div>
      </div>
    </div>
  );
}
