'use client';

import React from 'react';
import {
  Building2,
  Users,
  CheckCircle2,
  AlertCircle,
  DollarSign,
  Brain,
  Lightbulb,
  ArrowRight,
  ShieldCheck,
  Zap,
  Activity
} from 'lucide-react';
import { TodayStats, AIEmployeeSpec, TaskRecord } from '@/types';

interface CommandCenterProps {
  todayStats: TodayStats | null;
  employees: AIEmployeeSpec[];
  tasks: TaskRecord[];
  onEnterHQ: () => void;
  onEnterOffice: (employee: AIEmployeeSpec) => void;
}

export default function CommandCenter({
  todayStats,
  employees,
  tasks,
  onEnterHQ,
  onEnterOffice
}: CommandCenterProps) {
  const currentDate = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  });

  const awaitingCount = todayStats?.tasks_awaiting_approval ?? tasks.filter((t) => t.status === 'waiting_approval').length;
  const completedCount = todayStats?.tasks_completed ?? tasks.filter((t) => t.status === 'completed').length;
  const totalCost = todayStats?.total_ai_cost_usd ?? 0;
  const lessonsToday = todayStats?.lessons_learned_today ?? 0;
  const proposedPending = todayStats?.proposed_memories_pending ?? 0;

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-12">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-2 border-b border-white/[0.06]">
        <div>
          <div className="flex items-center gap-2.5 text-xs text-indigo-400 font-semibold uppercase tracking-wider mb-1">
            <Activity className="w-4 h-4" />
            <span>Executive Command Center</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight">Today at Webshastraa AI</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Real-time daily operations telemetry across all 4 autonomous digital employees.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-zinc-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="font-medium">{currentDate}</span>
        </div>
      </div>

      {/* 6 Key Stat Tiles */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3.5">
        {/* 1. Employees Online */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-4 space-y-1.5 shadow-lg relative overflow-hidden">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <Users className="w-3.5 h-3.5 text-indigo-400" />
              Workforce
            </span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          </div>
          <div className="text-2xl font-black text-white">{employees.length}</div>
          <div className="text-[11px] text-zinc-500 font-medium">Digital Employees</div>
        </div>

        {/* 2. Tasks Completed Today */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-4 space-y-1.5 shadow-lg relative overflow-hidden">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <CheckCircle2 className="w-3.5 h-3.5 text-emerald-400" />
              Completed
            </span>
            <span className="text-[10px] font-bold text-emerald-400 bg-emerald-500/10 px-1.5 py-0.5 rounded">
              Today
            </span>
          </div>
          <div className="text-2xl font-black text-emerald-400">{completedCount}</div>
          <div className="text-[11px] text-zinc-500 font-medium">Missions Finished</div>
        </div>

        {/* 3. Awaiting Approval */}
        <div
          onClick={onEnterHQ}
          className={`rounded-2xl border p-4 space-y-1.5 shadow-lg relative overflow-hidden transition cursor-pointer ${
            awaitingCount > 0
              ? 'border-amber-500/30 bg-amber-500/10 hover:bg-amber-500/20'
              : 'border-white/[0.08] bg-[#0c101c]/80'
          }`}
        >
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <AlertCircle className={`w-3.5 h-3.5 ${awaitingCount > 0 ? 'text-amber-400' : 'text-zinc-500'}`} />
              Approvals
            </span>
            {awaitingCount > 0 && <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />}
          </div>
          <div className={`text-2xl font-black ${awaitingCount > 0 ? 'text-amber-400' : 'text-zinc-400'}`}>
            {awaitingCount}
          </div>
          <div className="text-[11px] text-zinc-500 font-medium">Pending Sign-off</div>
        </div>

        {/* 4. AI Compute Cost Today */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-4 space-y-1.5 shadow-lg relative overflow-hidden">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <DollarSign className="w-3.5 h-3.5 text-purple-400" />
              API Burn
            </span>
            <span className="text-[10px] font-mono text-zinc-500">Gemini</span>
          </div>
          <div className="text-xl font-black text-white font-mono tracking-tight">${totalCost.toFixed(4)}</div>
          <div className="text-[11px] text-zinc-500 font-medium">Compute Cost</div>
        </div>

        {/* 5. Lessons Learned */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-4 space-y-1.5 shadow-lg relative overflow-hidden">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <Brain className="w-3.5 h-3.5 text-blue-400" />
              Learned
            </span>
            <span className="text-[10px] text-blue-400 bg-blue-500/10 px-1.5 py-0.5 rounded font-bold">Rules</span>
          </div>
          <div className="text-2xl font-black text-blue-400">{lessonsToday}</div>
          <div className="text-[11px] text-zinc-500 font-medium">Active Memories</div>
        </div>

        {/* 6. Proposed Pending Review */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-4 space-y-1.5 shadow-lg relative overflow-hidden">
          <div className="flex items-center justify-between text-zinc-400 text-xs">
            <span className="flex items-center gap-1.5 font-medium">
              <Lightbulb className="w-3.5 h-3.5 text-violet-400" />
              Proposed
            </span>
            <span className="text-[10px] text-violet-400 bg-violet-500/10 px-1.5 py-0.5 rounded font-bold">Reflect</span>
          </div>
          <div className="text-2xl font-black text-violet-300">{proposedPending}</div>
          <div className="text-[11px] text-zinc-500 font-medium">Awaiting Review</div>
        </div>
      </div>

      {/* Main Floorplan CTA Card */}
      <div className="relative rounded-3xl border border-white/[0.1] bg-gradient-to-r from-indigo-950/40 via-[#0c101c] to-purple-950/30 p-8 overflow-hidden shadow-2xl flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="space-y-2 max-w-xl">
          <span className="text-[11px] font-bold px-3 py-1 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 uppercase tracking-wider inline-block">
            HQ Virtual Floorplan
          </span>
          <h2 className="text-2xl font-black text-white tracking-tight">
            Step onto the Executive Floor
          </h2>
          <p className="text-xs text-zinc-300 leading-relaxed">
            Maya, Arjun, Chloe, and David each maintain a dedicated digital office suite complete with their behavioral persona, active memory vault, tool permissions, and task consoles.
          </p>
        </div>

        <button
          type="button"
          onClick={onEnterHQ}
          className="flex items-center justify-center gap-2.5 px-6 py-3.5 rounded-2xl text-xs font-bold text-white bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 transition shadow-xl shadow-indigo-600/30 active:scale-95 cursor-pointer shrink-0"
        >
          <Building2 className="w-4 h-4" />
          <span>Enter HQ Floorplan</span>
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {/* Per-Employee Today Summary Cards */}
      <div className="space-y-3">
        <span className="text-xs font-bold text-zinc-400 uppercase tracking-wider block">
          Workforce Status by Executive Suite
        </span>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {employees.map((emp) => {
            const todayEmp = todayStats?.per_employee.find((p) => p.employee_id === emp.id);
            const empTasks = tasks.filter((t) => t.employee_id === emp.id);
            const awaiting = todayEmp?.awaiting_approval ?? empTasks.filter((t) => t.status === 'waiting_approval').length;
            const completed = todayEmp?.completed ?? empTasks.filter((t) => t.status === 'completed').length;
            const activeMem = todayEmp?.active_memories ?? 0;

            return (
              <div
                key={emp.id}
                onClick={() => onEnterOffice(emp)}
                className="rounded-2xl border border-white/[0.08] bg-[#0c101c]/80 backdrop-blur-xl p-5 space-y-4 hover:border-white/[0.16] hover:bg-white/[0.02] transition cursor-pointer group"
              >
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center text-xl">
                      {emp.avatar_emoji || '🤖'}
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-white group-hover:text-indigo-300 transition">
                        {emp.name}
                      </h3>
                      <p className="text-[10px] text-zinc-500">{emp.department}</p>
                    </div>
                  </div>
                  {awaiting > 0 ? (
                    <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                  ) : (
                    <span className="w-2 h-2 rounded-full bg-emerald-400" />
                  )}
                </div>

                <div className="grid grid-cols-3 gap-2 text-center pt-1 border-t border-white/[0.04]">
                  <div>
                    <span className="text-[9px] text-zinc-500 block uppercase">Done</span>
                    <span className="text-xs font-bold text-white">{completed}</span>
                  </div>
                  <div>
                    <span className="text-[9px] text-zinc-500 block uppercase">Pending</span>
                    <span className={`text-xs font-bold ${awaiting > 0 ? 'text-amber-400' : 'text-zinc-400'}`}>
                      {awaiting}
                    </span>
                  </div>
                  <div>
                    <span className="text-[9px] text-zinc-500 block uppercase">Rules</span>
                    <span className="text-xs font-bold text-indigo-300">{activeMem}</span>
                  </div>
                </div>

                <div className="flex items-center justify-between pt-1 text-[11px] text-zinc-500 group-hover:text-indigo-300 transition">
                  <span>Enter Suite</span>
                  <ArrowRight className="w-3 h-3 group-hover:translate-x-0.5 transition" />
                </div>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
