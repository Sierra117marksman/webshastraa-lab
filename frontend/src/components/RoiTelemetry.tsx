'use client';

import React from 'react';
import { Clock, DollarSign, Activity, ShieldCheck, Zap } from 'lucide-react';
import { AnalyticsData } from '@/types';

interface RoiTelemetryProps {
  analytics: AnalyticsData;
}

export default function RoiTelemetry({ analytics }: RoiTelemetryProps) {
  return (
    <div id="tour-telemetry" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3.5 mb-8">
      {/* Hours Saved Metric */}
      <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e1320]/90 to-[#090c15]/90 p-4 space-y-1.5 shadow-lg relative overflow-hidden">
        <div className="flex items-center justify-between text-zinc-400 text-xs">
          <span className="flex items-center gap-1.5 font-medium">
            <Clock className="w-3.5 h-3.5 text-indigo-400" />
            Hours Saved
          </span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-indigo-500/10 text-indigo-300 border border-indigo-500/20">
            {analytics.completed_tasks} Tasks
          </span>
        </div>
        <div className="text-xl font-black text-white tracking-tight">
          {analytics.hours_saved} <span className="text-xs font-semibold text-zinc-400">hrs</span>
        </div>
        <div className="text-[11px] text-zinc-400">
          Equivalent to <strong className="text-emerald-400 font-mono">${analytics.human_cost_equivalent_usd.toFixed(2)}</strong> in VA labor
        </div>
        <div className="absolute -right-6 -bottom-6 w-16 h-16 bg-indigo-500/10 rounded-full blur-xl pointer-events-none" />
      </div>

      {/* Net Value & Margin */}
      <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e1320]/90 to-[#090c15]/90 p-4 space-y-1.5 shadow-lg relative overflow-hidden">
        <div className="flex items-center justify-between text-zinc-400 text-xs">
          <span className="flex items-center gap-1.5 font-medium">
            <DollarSign className="w-3.5 h-3.5 text-emerald-400" />
            Net Value Created
          </span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
            99.9% Margin
          </span>
        </div>
        <div className="text-xl font-black text-emerald-400 tracking-tight">
          +${analytics.net_savings_usd.toFixed(2)}
        </div>
        <div className="text-[11px] text-zinc-400">
          Gross savings minus API compute burn
        </div>
        <div className="absolute -right-6 -bottom-6 w-16 h-16 bg-emerald-500/10 rounded-full blur-xl pointer-events-none" />
      </div>

      {/* API Cost / Burn Control */}
      <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e1320]/90 to-[#090c15]/90 p-4 space-y-1.5 shadow-lg relative overflow-hidden">
        <div className="flex items-center justify-between text-zinc-400 text-xs">
          <span className="flex items-center gap-1.5 font-medium">
            <Activity className="w-3.5 h-3.5 text-purple-400" />
            Total API Compute
          </span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-purple-500/10 text-purple-300 border border-purple-500/20">
            Gemini 3.6 Flash
          </span>
        </div>
        <div className="text-xl font-black text-white font-mono tracking-tight">
          ${analytics.total_cost_usd.toFixed(4)}
        </div>
        <div className="text-[11px] text-zinc-400">
          Max 3 steps circuit breaker active
        </div>
        <div className="absolute -right-6 -bottom-6 w-16 h-16 bg-purple-500/10 rounded-full blur-xl pointer-events-none" />
      </div>

      {/* Safety & Governance */}
      <div className="rounded-2xl border border-white/[0.08] bg-gradient-to-b from-[#0e1320]/90 to-[#090c15]/90 p-4 space-y-1.5 shadow-lg relative overflow-hidden">
        <div className="flex items-center justify-between text-zinc-400 text-xs">
          <span className="flex items-center gap-1.5 font-medium">
            <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
            Safety & Blacklist
          </span>
          <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            Enforced
          </span>
        </div>
        <div className="text-sm font-bold text-white tracking-tight flex items-center gap-1.5 pt-0.5">
          <Zap className="w-4 h-4 text-amber-400" />
          <span>Zero Rogue Actions</span>
        </div>
        <div className="text-[11px] text-zinc-400">
          Outbound emails require 1-click founder sign-off
        </div>
        <div className="absolute -right-6 -bottom-6 w-16 h-16 bg-amber-500/10 rounded-full blur-xl pointer-events-none" />
      </div>
    </div>
  );
}
