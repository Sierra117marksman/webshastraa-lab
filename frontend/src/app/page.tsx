'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Menu, Compass } from 'lucide-react';
import Sidebar from '@/components/Sidebar';
import HireStudio from '@/components/HireStudio';
import RosterView from '@/components/RosterView';
import ApprovalFeed from '@/components/ApprovalFeed';
import SettingsView from '@/components/SettingsView';
import RoiTelemetry from '@/components/RoiTelemetry';
import CoachMarkTour from '@/components/CoachMarkTour';
import { AIEmployeeSpec, TaskRecord, SettingsState, AnalyticsData } from '@/types';

const DEFAULT_API_BASE = process.env.NEXT_PUBLIC_API_BASE || 'https://webshastraa-lab.onrender.com';

export default function Home() {
  const [activeTab, setActiveTab] = useState<'hire' | 'roster' | 'feed' | 'settings'>('roster');
  const [employees, setEmployees] = useState<AIEmployeeSpec[]>([]);
  const [tasks, setTasks] = useState<TaskRecord[]>([]);
  const [dispatchingId, setDispatchingId] = useState<string | null>(null);
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false);
  const [isTourOpen, setIsTourOpen] = useState(false);
  const [apiBase, setApiBase] = useState<string>(DEFAULT_API_BASE);
  const [isBackendOnline, setIsBackendOnline] = useState<boolean>(true);

  const [analytics, setAnalytics] = useState<AnalyticsData>({
    total_tasks: 0,
    completed_tasks: 0,
    hours_saved: 0,
    total_cost_usd: 0,
    human_cost_equivalent_usd: 0,
    net_savings_usd: 0
  });

  const [settings, setSettings] = useState<SettingsState>({
    gemini_connected: true,
    tavily_connected: true,
    tavily_key_preview: 'tvly-d...',
    smtp_user: 'webshastraa@gmail.com',
    smtp_has_pass: false,
    active_email_sender: 'uk.indranijewels@gmail.com',
    smtp_active: true,
    blacklist_domains: 'investor.com,board.com,vip.com,internal.com'
  });

  useEffect(() => {
    const saved = localStorage.getItem('webshastraa_api_base');
    if (saved) {
      setTimeout(() => {
        setApiBase(saved);
      }, 0);
    }
  }, []);

  const fetchData = useCallback(async (targetBase?: string) => {
    const base = targetBase || apiBase;
    try {
      const [empRes, taskRes, setRes, anaRes] = await Promise.all([
        fetch(`${base}/api/employees`),
        fetch(`${base}/api/tasks`),
        fetch(`${base}/api/settings`),
        fetch(`${base}/api/analytics`)
      ]);
      if (empRes.ok) setEmployees(await empRes.json());
      if (taskRes.ok) setTasks(await taskRes.json());
      if (setRes.ok) setSettings(await setRes.json());
      if (anaRes.ok) setAnalytics(await anaRes.json());
      setIsBackendOnline(true);
    } catch (err) {
      console.error('Failed to sync state:', err);
      setIsBackendOnline(false);
    }
  }, [apiBase]);

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchData();
    }, 0);
    const interval = setInterval(() => {
      fetchData();
    }, 3500);

    // Auto-trigger tour on first visit
    const hasSeenTour = localStorage.getItem('webshastraa_tour_seen');
    let tourTimer: NodeJS.Timeout | null = null;
    if (!hasSeenTour) {
      tourTimer = setTimeout(() => {
        setIsTourOpen(true);
        localStorage.setItem('webshastraa_tour_seen', 'true');
      }, 1000);
    }

    return () => {
      clearTimeout(timer);
      clearInterval(interval);
      if (tourTimer) clearTimeout(tourTimer);
    };
  }, [fetchData]);

  const handleUpdateApiBase = (newBase: string) => {
    setApiBase(newBase);
    localStorage.setItem('webshastraa_api_base', newBase);
    fetchData(newBase);
  };

  const handleDispatch = async (employeeId: string, customPrompt?: string) => {
    setDispatchingId(employeeId);
    try {
      const res = await fetch(`${apiBase}/api/employees/${employeeId}/dispatch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ task_prompt: customPrompt || undefined })
      });
      if (res.ok) {
        await fetchData();
        setActiveTab('feed');
      }
    } catch {
      alert(`Failed to dispatch task. Please verify backend is running at ${apiBase}`);
    } finally {
      setDispatchingId(null);
    }
  };

  const handleDelete = async (employeeId: string) => {
    if (!confirm('Are you sure you want to dismiss this AI employee from your company?')) return;
    await fetch(`${apiBase}/api/employees/${employeeId}`, { method: 'DELETE' });
    fetchData();
  };

  const handleApprove = async (taskId: string, approved: boolean) => {
    try {
      const res = await fetch(`${apiBase}/api/tasks/${taskId}/approve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved })
      });
      if (res.ok) {
        fetchData();
      }
    } catch {
      alert('Approval request failed.');
    }
  };

  const handleSaveSettings = async (payload: { tavily_api_key?: string; smtp_user?: string; smtp_pass?: string; blacklist_domains?: string }) => {
    try {
      const res = await fetch(`${apiBase}/api/settings`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        const data = await res.json();
        setSettings(data.settings);
      }
    } catch {
      alert('Failed to update settings.');
    }
  };

  const pendingApprovalsCount = tasks.filter((t) => t.status === 'waiting_approval').length;

  return (
    <div className="flex min-h-screen bg-[#06080d] text-zinc-100 font-sans antialiased selection:bg-indigo-500/30 selection:text-indigo-200">
      {/* Interactive Coach Mark Walkthrough */}
      <CoachMarkTour
        isOpen={isTourOpen}
        onClose={() => setIsTourOpen(false)}
        setActiveTab={setActiveTab}
      />

      {/* Sidebar Navigation (Desktop Persistent + Mobile Drawer) */}
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        employeeCount={employees.length}
        pendingApprovalsCount={pendingApprovalsCount}
        settings={settings}
        isOpen={isMobileMenuOpen}
        onClose={() => setIsMobileMenuOpen(false)}
        onStartTour={() => setIsTourOpen(true)}
      />

      {/* Main Studio Viewport */}
      <div className="flex-1 flex flex-col min-w-0 overflow-y-auto h-screen">
        {/* Subtle Ambient Radial Glow */}
        <div className="fixed top-0 right-1/4 w-[600px] h-[300px] bg-gradient-to-b from-indigo-500/10 via-purple-500/5 to-transparent blur-3xl pointer-events-none -z-10" />

        {/* Mobile Top Navigation Header */}
        <header className="md:hidden flex items-center justify-between px-4 py-3 border-b border-white/[0.08] bg-[#07090f]/90 backdrop-blur-xl sticky top-0 z-20">
          <div className="flex items-center gap-2.5">
            <button
              type="button"
              onClick={() => setIsMobileMenuOpen(true)}
              className="p-2 rounded-xl text-zinc-400 hover:text-white bg-white/[0.04] border border-white/[0.06] transition cursor-pointer"
              aria-label="Open Navigation Menu"
            >
              <Menu className="w-5 h-5" />
            </button>
            <div className="flex items-center gap-1.5">
              <span className="font-black text-sm tracking-tight text-white">Webshastraa AI</span>
              <span className="text-[9px] font-bold tracking-widest px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                BETA
              </span>
            </div>
          </div>

          <button
            type="button"
            onClick={() => setIsTourOpen(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold text-indigo-300 bg-indigo-500/10 border border-indigo-500/30 transition shadow-sm cursor-pointer active:scale-95"
          >
            <Compass className="w-3.5 h-3.5 text-indigo-400" />
            <span>Tour</span>
          </button>
        </header>

        {/* Desktop Quick Header */}
        <header className="hidden md:flex items-center justify-between px-8 py-3.5 border-b border-white/[0.04] bg-transparent">
          <div className="flex items-center gap-2 text-xs text-zinc-400">
            <span>Workspace: <strong className="text-zinc-200">Webshastraa Labs</strong></span>
            <span className="text-zinc-600">•</span>
            <span className="text-emerald-400 flex items-center gap-1">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              Autonomous Engine Active
            </span>
          </div>

          <button
            type="button"
            onClick={() => setIsTourOpen(true)}
            className="flex items-center gap-2 px-3.5 py-1.5 rounded-xl text-xs font-bold text-indigo-300 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/30 transition shadow-sm cursor-pointer group"
          >
            <Compass className="w-3.5 h-3.5 text-indigo-400 group-hover:rotate-45 transition duration-300" />
            <span>Interactive Tour & Coach Marks</span>
          </button>
        </header>

        {/* Backend Connection Alert Banner */}
        {!isBackendOnline && (
          <div className="bg-amber-500/10 border-b border-amber-500/20 px-4 sm:px-8 py-2.5 text-xs text-amber-300 flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse shrink-0" />
              <span>
                <strong>Backend Disconnected:</strong> Cannot reach <code>{apiBase}</code>. If on mobile, configure your public endpoint in Settings.
              </span>
            </div>
            <button
              type="button"
              onClick={() => setActiveTab('settings')}
              className="px-2.5 py-1 rounded-lg bg-amber-500/20 hover:bg-amber-500/30 text-amber-200 border border-amber-500/30 font-semibold cursor-pointer transition text-[11px] shrink-0"
            >
              Configure Endpoint &rarr;
            </button>
          </div>
        )}

        <main className="flex-1 p-4 sm:p-6 md:p-10 max-w-7xl w-full mx-auto">
          {/* Executive Telemetry & Value Creation Strip */}
          <RoiTelemetry analytics={analytics} />

          {activeTab === 'hire' && (
            <HireStudio
              apiBase={apiBase}
              onEmployeeHired={(newEmp) => {
                setEmployees((prev) => [newEmp, ...prev]);
                setActiveTab('roster');
              }}
            />
          )}

          {activeTab === 'roster' && (
            <RosterView
              employees={employees}
              onDispatch={handleDispatch}
              onDelete={handleDelete}
              dispatchingId={dispatchingId}
            />
          )}

          {activeTab === 'feed' && (
            <ApprovalFeed
              tasks={tasks}
              onApprove={handleApprove}
              activeEmailSender={settings.active_email_sender}
            />
          )}

          {activeTab === 'settings' && (
            <SettingsView
              settings={settings}
              onSave={handleSaveSettings}
              apiBase={apiBase}
              onUpdateApiBase={handleUpdateApiBase}
            />
          )}
        </main>
      </div>
    </div>
  );
}
