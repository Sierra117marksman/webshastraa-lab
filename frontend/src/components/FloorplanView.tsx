'use client';

import React from 'react';
import { Building2, ArrowRight, ShieldCheck, Activity, Brain, Clock } from 'lucide-react';
import { AIEmployeeSpec, TaskRecord, TodayStats } from '@/types';

interface FloorplanViewProps {
  employees: AIEmployeeSpec[];
  tasks: TaskRecord[];
  todayStats: TodayStats | null;
  apiBase: string;
  onEnterOffice: (employee: AIEmployeeSpec) => void;
}

const THEME_CARD_STYLES: Record<string, { border: string; glow: string; badge: string; bgGradient: string }> = {
  indigo: {
    border: 'border-indigo-500/30 hover:border-indigo-400/60',
    glow: 'group-hover:shadow-indigo-500/10',
    badge: 'bg-indigo-500/20 text-indigo-300 border-indigo-500/30',
    bgGradient: 'from-indigo-950/20 via-transparent to-transparent'
  },
  violet: {
    border: 'border-violet-500/30 hover:border-violet-400/60',
    glow: 'group-hover:shadow-violet-500/10',
    badge: 'bg-violet-500/20 text-violet-300 border-violet-500/30',
    bgGradient: 'from-violet-950/20 via-transparent to-transparent'
  },
  rose: {
    border: 'border-rose-500/30 hover:border-rose-400/60',
    glow: 'group-hover:shadow-rose-500/10',
    badge: 'bg-rose-500/20 text-rose-300 border-rose-500/30',
    bgGradient: 'from-rose-950/20 via-transparent to-transparent'
  },
  amber: {
    border: 'border-amber-500/30 hover:border-amber-400/60',
    glow: 'group-hover:shadow-amber-500/10',
    badge: 'bg-amber-500/20 text-amber-300 border-amber-500/30',
    bgGradient: 'from-amber-950/20 via-transparent to-transparent'
  },
  emerald: {
    border: 'border-emerald-500/30 hover:border-emerald-400/60',
    glow: 'group-hover:shadow-emerald-500/10',
    badge: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30',
    bgGradient: 'from-emerald-950/20 via-transparent to-transparent'
  },
  sky: {
    border: 'border-sky-500/30 hover:border-sky-400/60',
    glow: 'group-hover:shadow-sky-500/10',
    badge: 'bg-sky-500/20 text-sky-300 border-sky-500/30',
    bgGradient: 'from-sky-950/20 via-transparent to-transparent'
  }
};

export default function FloorplanView({
  employees,
  tasks,
  todayStats,
  onEnterOffice
}: FloorplanViewProps) {
  const currentDate = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    year: 'numeric',
    month: 'long',
    day: 'numeric'
  });

  return (
    <div className="space-y-8 animate-in fade-in duration-300 pb-12">
      {/* Floorplan Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 pb-2 border-b border-white/[0.06]">
        <div>
          <div className="flex items-center gap-2.5 text-xs text-indigo-400 font-semibold uppercase tracking-wider mb-1">
            <Building2 className="w-4 h-4" />
            <span>Virtual Headquarters</span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-black text-white tracking-tight">Executive Floorplan</h1>
          <p className="text-xs text-zinc-400 mt-1">
            Select an executive suite to enter an autonomous office, inspect active memories, and govern tool actions.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs text-zinc-400">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span className="font-medium">{currentDate}</span>
        </div>
      </div>

      {/* 4 Office Door Cards Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-2 gap-6">
        {employees.map((emp) => {
          const empStyle = THEME_CARD_STYLES[emp.theme_color] || THEME_CARD_STYLES.indigo;
          const empTasks = tasks.filter((t) => t.employee_id === emp.id);
          const hasWaiting = empTasks.some((t) => t.status === 'waiting_approval');
          const isRunning = empTasks.some((t) => t.status === 'running');

          // Today metrics for this employee
          const todayEmp = todayStats?.per_employee.find((p) => p.employee_id === emp.id);
          const tasksRun = todayEmp?.tasks_run ?? empTasks.length;
          const awaitingCount = todayEmp?.awaiting_approval ?? empTasks.filter((t) => t.status === 'waiting_approval').length;
          const activeMemories = todayEmp?.active_memories ?? 0;

          return (
            <div
              key={emp.id}
              onClick={() => onEnterOffice(emp)}
              className={`group relative rounded-3xl border ${empStyle.border} bg-[#0c101c]/80 backdrop-blur-xl p-6 sm:p-7 transition-all duration-300 hover:scale-[1.01] hover:shadow-2xl ${empStyle.glow} cursor-pointer flex flex-col justify-between overflow-hidden`}
            >
              {/* Subtle background gradient based on theme */}
              <div
                className={`absolute inset-0 bg-gradient-to-br ${empStyle.bgGradient} opacity-50 group-hover:opacity-100 transition duration-500 pointer-events-none`}
              />

              <div className="relative z-10 space-y-5">
                {/* Door Header */}
                <div className="flex items-start justify-between gap-4">
                  <div className="flex items-center gap-4">
                    <div className="w-16 h-16 rounded-2xl bg-gradient-to-tr from-white/[0.08] to-white/[0.02] border border-white/[0.12] flex items-center justify-center text-3xl shadow-inner group-hover:scale-105 transition duration-300">
                      {emp.avatar_emoji || '🤖'}
                    </div>
                    <div>
                      <h2 className="text-xl font-black text-white tracking-tight group-hover:text-indigo-200 transition">
                        {emp.name}
                      </h2>
                      <p className="text-xs text-zinc-400 font-medium line-clamp-1">{emp.role}</p>
                      <span className={`inline-block mt-1 text-[10px] font-bold px-2 py-0.5 rounded border ${empStyle.badge}`}>
                        {emp.department}
                      </span>
                    </div>
                  </div>

                  {/* Status Indicator Pill */}
                  <div className="shrink-0">
                    {hasWaiting ? (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-amber-500/20 text-amber-300 border border-amber-500/30 animate-pulse">
                        <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                        Sign-off Needed
                      </span>
                    ) : isRunning ? (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-bold bg-sky-500/20 text-sky-300 border border-sky-500/30">
                        <span className="w-1.5 h-1.5 rounded-full bg-sky-400 animate-pulse" />
                        Executing
                      </span>
                    ) : (
                      <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[10px] font-semibold bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">
                        <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
                        At Desk
                      </span>
                    )}
                  </div>
                </div>

                {/* Persona / Objective snippet */}
                <p className="text-xs text-zinc-400 line-clamp-2 leading-relaxed bg-white/[0.02] p-3 rounded-xl border border-white/[0.04]">
                  {emp.objective}
                </p>

                {/* Today State Metric Strip */}
                <div className="grid grid-cols-3 gap-2.5 pt-1">
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-2.5 text-center">
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider block font-semibold">Today Runs</span>
                    <span className="text-base font-black text-white">{tasksRun}</span>
                  </div>
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-2.5 text-center">
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider block font-semibold">Awaiting</span>
                    <span className={`text-base font-black ${awaitingCount > 0 ? 'text-amber-400' : 'text-zinc-400'}`}>
                      {awaitingCount}
                    </span>
                  </div>
                  <div className="rounded-xl bg-white/[0.03] border border-white/[0.06] p-2.5 text-center">
                    <span className="text-[10px] text-zinc-500 uppercase tracking-wider block font-semibold">Memories</span>
                    <span className="text-base font-black text-indigo-300">{activeMemories}</span>
                  </div>
                </div>
              </div>

              {/* Enter Door CTA Footer */}
              <div className="relative z-10 pt-5 mt-4 border-t border-white/[0.06] flex items-center justify-between">
                <span className="text-xs text-zinc-400 group-hover:text-zinc-200 transition font-medium">
                  Enter Executive Suite
                </span>
                <div className="w-7 h-7 rounded-xl bg-white/[0.04] group-hover:bg-white/[0.1] border border-white/[0.08] flex items-center justify-center text-zinc-400 group-hover:text-white group-hover:translate-x-0.5 transition duration-300">
                  <ArrowRight className="w-3.5 h-3.5" />
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
