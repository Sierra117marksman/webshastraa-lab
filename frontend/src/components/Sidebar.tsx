'use client';

import React from 'react';
import {
  Sparkles,
  Users,
  BarChart3,
  KeyRound,
  Bot,
  Mail,
  Globe,
  Zap,
  ChevronRight,
  ShieldCheck,
  Compass,
  X,
  LayoutGrid,
  Activity
} from 'lucide-react';
import { SettingsState } from '@/types';

export type ActiveTab = 'studio' | 'hq' | 'floorplan' | 'office' | 'hire' | 'roster' | 'feed' | 'settings';

interface SidebarProps {
  activeTab: ActiveTab;
  setActiveTab: (tab: ActiveTab) => void;
  employeeCount: number;
  pendingApprovalsCount: number;
  settings: SettingsState;
  isOpen?: boolean;
  onClose?: () => void;
  onStartTour?: () => void;
}

export default function Sidebar({
  activeTab,
  setActiveTab,
  employeeCount,
  pendingApprovalsCount,
  settings,
  isOpen = false,
  onClose,
  onStartTour
}: SidebarProps) {
  const navItems: {
    id: ActiveTab;
    label: string;
    icon: React.ElementType;
    tag?: string;
    count?: number;
    alert?: number | null;
  }[] = [
    {
      id: 'studio',
      label: 'AI Employee Studio',
      icon: Sparkles,
      tag: 'Main'
    },
    {
      id: 'feed',
      label: 'Approvals & History',
      icon: BarChart3,
      alert: pendingApprovalsCount > 0 ? pendingApprovalsCount : null
    },
    {
      id: 'hq',
      label: 'Daily Telemetry',
      icon: Activity,
      tag: 'Stats'
    },
    {
      id: 'hire',
      label: 'Hire New AI',
      icon: Users,
      count: employeeCount
    },
    {
      id: 'settings',
      label: 'Settings & Keys',
      icon: KeyRound,
      tag: settings.tavily_connected ? 'Connected' : 'Setup'
    }
  ];

  const renderSidebarContent = () => (
    <div className="flex flex-col justify-between h-full">
      {/* Brand & Workspace */}
      <div className="p-5 space-y-6">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-tr from-indigo-500 via-indigo-600 to-violet-600 flex items-center justify-center text-white shadow-lg shadow-indigo-500/30 ring-1 ring-white/20">
              <Bot className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-1.5">
                <span className="font-extrabold text-sm tracking-tight text-white">Webshastraa AI</span>
                <span className="text-[9px] font-bold tracking-widest px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  BETA
                </span>
              </div>
              <p className="text-[10px] text-zinc-400 font-medium">Autonomous Enterprise Co-workers</p>
            </div>
          </div>

          {/* Close button on mobile */}
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              className="md:hidden p-1.5 rounded-lg text-zinc-400 hover:text-white bg-white/[0.05] hover:bg-white/[0.1] transition cursor-pointer"
            >
              <X className="w-4 h-4" />
            </button>
          )}
        </div>

        {/* Workspace Card */}
        <div
          onClick={() => {
            setActiveTab('studio');
            if (onClose) onClose();
          }}
          className="p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] flex items-center justify-between group hover:bg-white/[0.05] transition cursor-pointer"
        >
          <div className="flex items-center gap-2.5">
            <div className="w-6 h-6 rounded-md bg-gradient-to-br from-violet-600 to-indigo-700 flex items-center justify-center text-[10px] font-bold text-white shadow">
              W
            </div>
            <div className="text-left">
              <div className="text-xs font-semibold text-zinc-200">Webshastraa Labs</div>
              <div className="text-[10px] text-zinc-500">Cohort 4 • Stealth</div>
            </div>
          </div>
          <ChevronRight className="w-3.5 h-3.5 text-zinc-600 group-hover:text-zinc-400 group-hover:translate-x-0.5 transition" />
        </div>

        {/* Interactive Tour Trigger Button */}
        {onStartTour && (
          <button
            type="button"
            onClick={() => {
              if (onClose) onClose();
              onStartTour();
            }}
            className="w-full flex items-center justify-between px-3.5 py-2.5 rounded-xl text-xs font-bold text-indigo-300 bg-gradient-to-r from-indigo-500/10 to-violet-500/10 hover:from-indigo-500/20 hover:to-violet-500/20 border border-indigo-500/30 transition shadow-sm cursor-pointer group"
          >
            <div className="flex items-center gap-2.5">
              <Compass className="w-4 h-4 text-indigo-400 group-hover:rotate-45 transition duration-300" />
              <span>Platform Tour</span>
            </div>
            <span className="text-[9px] uppercase tracking-wider font-extrabold px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300">
              Guide
            </span>
          </button>
        )}

        {/* Navigation items */}
        <nav id="tour-sidebar" className="space-y-1">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-zinc-500 px-3 py-1">
            Platform Menu
          </div>
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = activeTab === item.id;
            return (
              <button
                key={item.id}
                type="button"
                onClick={() => {
                  setActiveTab(item.id);
                  if (onClose) onClose();
                }}
                className={`w-full flex items-center justify-between px-3 py-2.5 rounded-xl text-xs font-medium transition group cursor-pointer ${
                  isActive
                    ? 'bg-gradient-to-r from-indigo-600/20 to-violet-600/10 text-white font-semibold border border-indigo-500/30 shadow-sm'
                    : 'text-zinc-400 hover:text-zinc-200 hover:bg-white/[0.04]'
                }`}
              >
                <div className="flex items-center gap-2.5">
                  <Icon
                    className={`w-4 h-4 transition ${
                      isActive ? 'text-indigo-400' : 'text-zinc-500 group-hover:text-zinc-300'
                    }`}
                  />
                  <span>{item.label}</span>
                </div>

                {item.count !== undefined && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded-md bg-white/[0.06] text-zinc-400 font-mono">
                    {item.count}
                  </span>
                )}

                {item.tag && (
                  <span className="text-[9px] uppercase tracking-wider font-semibold px-1.5 py-0.5 rounded bg-white/[0.05] text-zinc-400">
                    {item.tag}
                  </span>
                )}

                {item.alert && (
                  <span className="flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-bold border border-amber-500/40 animate-pulse">
                    <span className="w-1.5 h-1.5 rounded-full bg-amber-400" />
                    {item.alert}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Cluster Status & Founder Profile */}
      <div className="p-4 border-t border-white/[0.08] space-y-4 bg-black/20">
        <div className="space-y-2 text-[11px]">
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5">
              <Zap className="w-3.5 h-3.5 text-indigo-400" /> Gemini 3.8 Flash
            </span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-sm shadow-emerald-500/50" />
          </div>
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5">
              <Globe className="w-3.5 h-3.5 text-indigo-400" /> Tavily Search
            </span>
            <span
              className={`w-2 h-2 rounded-full ${
                settings.tavily_connected ? 'bg-emerald-400 shadow-sm shadow-emerald-500/50' : 'bg-zinc-600'
              }`}
            />
          </div>
          <div className="flex items-center justify-between text-zinc-400">
            <span className="flex items-center gap-1.5">
              <Mail className="w-3.5 h-3.5 text-indigo-400" /> Gmail SMTP (465)
            </span>
            <span className="w-2 h-2 rounded-full bg-emerald-400 shadow-sm shadow-emerald-500/50" />
          </div>
        </div>

        <div className="pt-3 border-t border-white/[0.06] flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 rounded-lg bg-gradient-to-tr from-amber-500 to-rose-500 flex items-center justify-center font-bold text-white text-xs shadow">
              A
            </div>
            <div>
              <div className="text-xs font-semibold text-zinc-200">Ajay Thakkar</div>
              <div className="text-[10px] text-zinc-500">Founder Account</div>
            </div>
          </div>
          <ShieldCheck className="w-4 h-4 text-emerald-400" />
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Desktop Persistent Sidebar */}
      <aside className="hidden md:flex w-64 border-r border-white/[0.08] bg-[#07090f]/90 backdrop-blur-2xl flex-col justify-between shrink-0 h-screen sticky top-0 select-none z-30">
        {renderSidebarContent()}
      </aside>

      {/* Mobile Drawer */}
      {isOpen && (
        <div className="fixed inset-0 z-50 md:hidden flex animate-in fade-in duration-200">
          <div
            className="fixed inset-0 bg-black/80 backdrop-blur-sm cursor-pointer"
            onClick={onClose}
          />
          <aside className="relative w-72 max-w-[85vw] bg-[#07090f] border-r border-white/[0.08] flex flex-col justify-between h-full z-10 select-none shadow-2xl overflow-y-auto">
            {renderSidebarContent()}
          </aside>
        </div>
      )}
    </>
  );
}
