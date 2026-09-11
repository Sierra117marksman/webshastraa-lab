'use client';

import React, { useState } from 'react';
import {
  Users,
  Play,
  RefreshCw,
  Trash2,
  ChevronDown,
  ChevronUp
} from 'lucide-react';
import { AIEmployeeSpec } from '@/types';

interface RosterViewProps {
  employees: AIEmployeeSpec[];
  onDispatch: (employeeId: string, customPrompt?: string) => Promise<void>;
  onDelete: (employeeId: string) => Promise<void>;
  dispatchingId: string | null;
}

export default function RosterView({
  employees,
  onDispatch,
  onDelete,
  dispatchingId
}: RosterViewProps) {
  const [filterDept, setFilterDept] = useState<string>('All');
  const [taskInputs, setTaskInputs] = useState<{ [id: string]: string }>({});
  const [expandedSops, setExpandedSops] = useState<{ [id: string]: boolean }>({});

  const toggleSop = (id: string) => {
    setExpandedSops((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const departments = ['All', 'CRM', 'HRM', 'Marketing', 'Operations'];

  const filtered = filterDept === 'All'
    ? employees
    : employees.filter((e) => e.department.toLowerCase() === filterDept.toLowerCase());

  const getDeptColor = (dept: string) => {
    switch (dept.toLowerCase()) {
      case 'crm':
        return 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30';
      case 'hrm':
        return 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30';
      case 'marketing':
        return 'bg-purple-500/10 text-purple-400 border-purple-500/30';
      case 'operations':
        return 'bg-amber-500/10 text-amber-400 border-amber-500/30';
      default:
        return 'bg-zinc-500/10 text-zinc-400 border-zinc-500/30';
    }
  };

  return (
    <div id="tour-roster" className="space-y-6 max-w-6xl mx-auto">
      {/* Header & Department Filters */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-white/[0.08] pb-5">
        <div>
          <h2 className="text-2xl font-black text-white tracking-tight">Active Digital Workforce</h2>
          <p className="text-xs text-zinc-400 mt-1">
            {employees.length} autonomous co-workers deployed in your organization
          </p>
        </div>

        <div className="flex items-center gap-1.5 p-1 bg-white/[0.03] border border-white/[0.08] rounded-xl text-xs">
          {departments.map((dept) => {
            const count = dept === 'All'
              ? employees.length
              : employees.filter((e) => e.department.toLowerCase() === dept.toLowerCase()).length;
            return (
              <button
                key={dept}
                type="button"
                onClick={() => setFilterDept(dept)}
                className={`px-3 py-1.5 rounded-lg font-medium transition cursor-pointer ${
                  filterDept === dept
                    ? 'bg-white/[0.12] text-white font-bold shadow'
                    : 'text-zinc-400 hover:text-zinc-200'
                }`}
              >
                {dept} <span className="opacity-60 text-[10px]">({count})</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Employees Grid */}
      {filtered.length === 0 ? (
        <div className="text-center py-20 border border-dashed border-white/[0.1] rounded-3xl p-12 text-zinc-500 space-y-3">
          <Users className="w-8 h-8 mx-auto text-zinc-600" />
          <div className="text-sm font-semibold text-zinc-300">No AI employees in this department yet</div>
          <p className="text-xs text-zinc-500">Go to Hire Studio to prompt and onboard a new co-worker.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          {filtered.map((emp) => {
            const isExpanded = expandedSops[emp.id] || false;
            const isRunning = dispatchingId === emp.id;
            return (
              <div
                key={emp.id}
                className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0c0f17]/90 to-[#07090f]/90 p-5 space-y-4 hover:border-white/[0.15] transition shadow-xl flex flex-col justify-between group"
              >
                {/* Top identity */}
                <div className="space-y-3">
                  <div className="flex items-start justify-between">
                    <div className="flex items-center gap-3.5">
                      <div className="w-12 h-12 rounded-xl bg-white/[0.04] border border-white/[0.1] flex items-center justify-center text-2xl shadow-inner group-hover:scale-105 transition">
                        {emp.avatar_emoji}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <h4 className="font-extrabold text-white text-base tracking-tight">{emp.name}</h4>
                          <span className={`text-[9px] font-bold px-2 py-0.5 rounded-full border uppercase ${getDeptColor(emp.department)}`}>
                            {emp.department}
                          </span>
                        </div>
                        <p className="text-xs font-semibold text-indigo-400 mt-0.5">{emp.role}</p>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={() => onDelete(emp.id)}
                      className="p-1.5 rounded-lg text-zinc-600 hover:text-rose-400 hover:bg-rose-500/10 transition cursor-pointer"
                      title="Dismiss Employee"
                    >
                      <Trash2 className="w-4 h-4" />
                    </button>
                  </div>

                  {/* Objective */}
                  <p className="text-xs text-zinc-300 leading-relaxed bg-black/20 p-3 rounded-xl border border-white/[0.04]">
                    {emp.objective}
                  </p>

                  {/* SOP Checklist Preview */}
                  <div className="space-y-1.5">
                    <button
                      type="button"
                      onClick={() => toggleSop(emp.id)}
                      className="w-full flex items-center justify-between text-[11px] font-bold text-zinc-400 uppercase tracking-wider hover:text-zinc-200 transition cursor-pointer"
                    >
                      <span>Standard Operating Procedures ({emp.sops.length})</span>
                      {isExpanded ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
                    </button>

                    {isExpanded ? (
                      <div className="p-3 rounded-xl bg-black/40 border border-white/[0.06] space-y-1.5 text-xs text-zinc-300">
                        {emp.sops.map((sop, i) => (
                          <div key={i} className="flex items-start gap-2 text-[11px] leading-relaxed">
                            <span className="text-indigo-400 font-extrabold">•</span>
                            <span>{sop}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-[11px] text-zinc-400 truncate">
                        • {emp.sops[0] || 'Analyze incoming requirements'}
                      </div>
                    )}
                  </div>

                  {/* Tools & Safety Badges */}
                  <div className="flex items-center justify-between pt-1 text-[11px]">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      {emp.tools.map((tool) => (
                        <span key={tool} className="px-2 py-0.5 rounded bg-white/[0.04] text-zinc-400 border border-white/[0.06] font-mono text-[10px]">
                          {tool}
                        </span>
                      ))}
                    </div>

                    {emp.requires_approval_for.length > 0 && (
                      <span className="text-[10px] text-amber-400 font-medium">
                        🛡️ Human sign-off required
                      </span>
                    )}
                  </div>
                </div>

                {/* Dispatch Mission Bar */}
                <div className="pt-3 border-t border-white/[0.06] space-y-2">
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={taskInputs[emp.id] || ''}
                      onChange={(e) => setTaskInputs({ ...taskInputs, [emp.id]: e.target.value })}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          onDispatch(emp.id, taskInputs[emp.id]);
                          setTaskInputs({ ...taskInputs, [emp.id]: '' });
                        }
                      }}
                      placeholder={`Assign task or leave empty for default mission...`}
                      className="flex-1 text-xs rounded-xl bg-black/40 border border-white/[0.08] px-3.5 py-2.5 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-indigo-500 transition"
                    />
                    <button
                      type="button"
                      onClick={() => {
                        onDispatch(emp.id, taskInputs[emp.id]);
                        setTaskInputs({ ...taskInputs, [emp.id]: '' });
                      }}
                      disabled={isRunning}
                      className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-xs font-bold text-white transition shadow-lg shadow-indigo-600/20 active:scale-95 cursor-pointer"
                    >
                      {isRunning ? (
                        <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      ) : (
                        <Play className="w-3.5 h-3.5 fill-white" />
                      )}
                      <span>Run</span>
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
