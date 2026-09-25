'use client';

import React from 'react';
import {
  Wrench,
  Brain,
  Lightbulb,
  ShieldCheck,
  ShieldX,
  CheckCircle2,
  XCircle,
  Clock,
  Loader2,
  ChevronRight
} from 'lucide-react';
import { TaskRecord, AuditLogEntry } from '@/types';

interface ExecutionMonitorProps {
  task: TaskRecord;
  auditLog: AuditLogEntry[];
}

interface TimelineEvent {
  key: string;
  ts: string;
  type: 'tool_call' | 'synthesis' | 'policy_pass' | 'policy_block' | 'memory_injected' | 'reflection_proposed' | 'approval_request' | 'approval_granted' | 'approval_rejected' | 'audit_other';
  label: string;
  detail?: string;
  metadata?: string;
}

function truncateOutput(val: unknown): string {
  if (val === undefined || val === null) return '';
  if (typeof val === 'string') {
    return val.length > 200 ? val.slice(0, 200) + '…' : val;
  }
  return 'Object result';
}

function formatParams(params: Record<string, unknown>): string {
  return Object.entries(params)
    .map(([k, v]) => `${k}: ${typeof v === 'string' ? v : JSON.stringify(v)}`)
    .join(' · ')
    .slice(0, 150);
}

function buildTimeline(task: TaskRecord, auditLog: AuditLogEntry[]): TimelineEvent[] {
  const events: TimelineEvent[] = [];

  task.steps.forEach((step) => {
    if (step.tool_called) {
      events.push({
        key: `step-${step.step_number}`,
        ts: step.timestamp,
        type: 'tool_call',
        label: step.tool_called,
        detail: truncateOutput(step.tool_output) || undefined
      });
    } else {
      events.push({
        key: `step-${step.step_number}`,
        ts: step.timestamp,
        type: 'synthesis',
        label: 'Direct synthesis',
        detail: truncateOutput(step.tool_output) || undefined
      });
    }
  });

  const taskAudit = auditLog.filter((e) => e.task_id === task.id);
  taskAudit.forEach((entry) => {
    const et = entry.event_type.toLowerCase();
    let type: TimelineEvent['type'] = 'audit_other';
    let label = entry.event_type;
    let detail = entry.output_summary;

    if (et.includes('policy_check_pass') || et === 'policy_pass') {
      type = 'policy_pass';
      label = 'Policy check passed';
    } else if (et.includes('policy_check_block') || et === 'policy_block') {
      type = 'policy_block';
      label = 'Policy check blocked';
      detail = entry.decision ?? entry.output_summary;
    } else if (et.includes('memory_inject')) {
      type = 'memory_injected';
      label = `${entry.memories_used.length} memories injected`;
    } else if (et.includes('reflection')) {
      type = 'reflection_proposed';
      label = 'Reflection proposed';
    } else if (et.includes('approval_request')) {
      type = 'approval_request';
      label = 'Approval requested';
    } else if (et.includes('approval_grant')) {
      type = 'approval_granted';
      label = 'Approved by founder';
    } else if (et.includes('approval_reject')) {
      type = 'approval_rejected';
      label = 'Rejected by founder';
      detail = entry.founder_feedback ?? detail;
    }

    events.push({
      key: `audit-${entry.id}`,
      ts: entry.timestamp,
      type,
      label,
      detail: detail.length > 200 ? detail.slice(0, 200) + '…' : detail
    });
  });

  events.sort((a, b) => a.ts.localeCompare(b.ts));
  return events;
}

function EventDot({ type }: { type: TimelineEvent['type'] }) {
  switch (type) {
    case 'tool_call': return <div className="w-2 h-2 rounded-full bg-indigo-400" />;
    case 'synthesis': return <div className="w-2 h-2 rounded-full bg-zinc-500" />;
    case 'policy_pass': return <div className="w-2 h-2 rounded-full bg-emerald-400" />;
    case 'policy_block': return <div className="w-2 h-2 rounded-full bg-red-400" />;
    case 'memory_injected': return <div className="w-2 h-2 rounded-full bg-purple-400" />;
    case 'reflection_proposed': return <div className="w-2 h-2 rounded-full bg-amber-400" />;
    case 'approval_request': return <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />;
    case 'approval_granted': return <div className="w-2 h-2 rounded-full bg-emerald-400" />;
    case 'approval_rejected': return <div className="w-2 h-2 rounded-full bg-red-400" />;
    default: return <div className="w-2 h-2 rounded-full bg-zinc-600" />;
  }
}

function EventIcon({ type }: { type: TimelineEvent['type'] }) {
  switch (type) {
    case 'tool_call': return <Wrench className="w-3 h-3 text-indigo-400" />;
    case 'synthesis': return <ChevronRight className="w-3 h-3 text-zinc-500" />;
    case 'policy_pass': return <ShieldCheck className="w-3 h-3 text-emerald-400" />;
    case 'policy_block': return <ShieldX className="w-3 h-3 text-red-400" />;
    case 'memory_injected': return <Brain className="w-3 h-3 text-purple-400" />;
    case 'reflection_proposed': return <Lightbulb className="w-3 h-3 text-amber-400" />;
    case 'approval_request': return <Clock className="w-3 h-3 text-amber-400" />;
    case 'approval_granted': return <CheckCircle2 className="w-3 h-3 text-emerald-400" />;
    case 'approval_rejected': return <XCircle className="w-3 h-3 text-red-400" />;
    default: return <ChevronRight className="w-3 h-3 text-zinc-500" />;
  }
}

function StatusBadge({ status }: { status: string }) {
  if (status === 'completed') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20">
        <CheckCircle2 className="w-4 h-4 text-emerald-400" />
        <span className="text-xs font-semibold text-emerald-300">Completed</span>
      </div>
    );
  }
  if (status === 'failed') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-red-500/10 border border-red-500/20">
        <XCircle className="w-4 h-4 text-red-400" />
        <span className="text-xs font-semibold text-red-300">Failed</span>
      </div>
    );
  }
  if (status === 'waiting_approval') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-amber-500/10 border border-amber-500/20">
        <Clock className="w-4 h-4 text-amber-400 animate-pulse" />
        <span className="text-xs font-semibold text-amber-300 animate-pulse">Awaiting Approval</span>
      </div>
    );
  }
  if (status === 'running') {
    return (
      <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-blue-500/10 border border-blue-500/20">
        <Loader2 className="w-4 h-4 text-blue-400 animate-spin" />
        <span className="text-xs font-semibold text-blue-300">Task running...</span>
      </div>
    );
  }
  return (
    <div className="flex items-center gap-2 px-3 py-2 rounded-xl bg-white/[0.04] border border-white/[0.06]">
      <span className="text-xs text-zinc-400 capitalize">{status}</span>
    </div>
  );
}

export default function ExecutionMonitor({ task, auditLog }: ExecutionMonitorProps) {
  const events = buildTimeline(task, auditLog);

  return (
    <div className="space-y-4">
      <div className="space-y-0">
        {events.length === 0 ? (
          <div className="text-center py-6">
            <Loader2 className="w-6 h-6 text-zinc-700 mx-auto mb-2 animate-spin" />
            <p className="text-xs text-zinc-500">Waiting for execution events...</p>
          </div>
        ) : (
          events.map((event, idx) => (
            <div key={event.key} className="flex gap-3">
              <div className="flex flex-col items-center">
                <div className="flex items-center justify-center w-5 h-5 shrink-0 mt-0.5">
                  <EventDot type={event.type} />
                </div>
                {idx < events.length - 1 && (
                  <div className="w-px flex-1 bg-white/[0.06] my-0.5" />
                )}
              </div>

              <div className={`pb-3 flex-1 min-w-0 ${idx === events.length - 1 ? '' : ''}`}>
                <div className="flex items-center gap-1.5 mb-0.5">
                  <EventIcon type={event.type} />
                  <span className="text-xs font-semibold text-zinc-300">{event.label}</span>
                  <span className="text-[10px] text-zinc-600 font-mono ml-auto shrink-0">
                    {new Date(event.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                </div>
                {event.detail && (
                  <p className="text-[11px] text-zinc-500 leading-relaxed bg-white/[0.02] rounded-lg px-2 py-1.5 mt-1">
                    {event.detail}
                  </p>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {task.status === 'running' && (
        <div className="flex items-center gap-2 text-xs text-blue-300 animate-pulse">
          <Loader2 className="w-3.5 h-3.5 animate-spin" />
          Task running...
        </div>
      )}

      <div className="pt-2 border-t border-white/[0.06]">
        <StatusBadge status={task.status} />
        {task.final_output && (
          <div className="mt-2 text-[11px] text-zinc-400 bg-white/[0.02] rounded-lg p-2.5 border border-white/[0.04]">
            <span className="font-semibold text-zinc-300">Output: </span>
            {task.final_output.slice(0, 300)}{task.final_output.length > 300 ? '…' : ''}
          </div>
        )}
        {(task.tokens_used || task.cost_usd) && (
          <div className="mt-1.5 flex gap-3 text-[10px] text-zinc-600">
            {task.tokens_used && <span>{task.tokens_used.toLocaleString()} tokens</span>}
            {task.cost_usd && <span>${task.cost_usd.toFixed(4)}</span>}
            {task.time_saved_mins && <span>{task.time_saved_mins} min saved</span>}
          </div>
        )}
      </div>
    </div>
  );
}
