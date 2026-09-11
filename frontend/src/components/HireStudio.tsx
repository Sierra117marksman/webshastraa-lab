'use client';

import React, { useState } from 'react';
import {
  Sparkles,
  RefreshCw,
  Check,
  ShieldCheck,
  ArrowRight,
  Zap
} from 'lucide-react';
import { AIEmployeeSpec } from '@/types';

interface HireStudioProps {
  onEmployeeHired: (emp: AIEmployeeSpec) => void;
  apiBase: string;
}

export default function HireStudio({ onEmployeeHired, apiBase }: HireStudioProps) {
  const [prompt, setPrompt] = useState('');
  const [isCompiling, setIsCompiling] = useState(false);
  const [compileStep, setCompileStep] = useState(0);
  const [compiledEmployee, setCompiledEmployee] = useState<AIEmployeeSpec | null>(null);

  const blueprints = [
    {
      role: 'Outbound B2B SDR',
      dept: 'CRM',
      icon: '🎯',
      desc: 'Finds early-stage founders on LinkedIn, enriches company signals, and drafts hyper-personalized 3-sentence cold emails.',
      prompt: 'I need an AI SDR to research seed to series-A tech founders on LinkedIn, extract their recent product announcements, craft high-converting cold outreach emails, and log them into our CRM spreadsheet.'
    },
    {
      role: 'Tech Talent Screener',
      dept: 'HRM',
      icon: '📋',
      desc: 'Parses candidate resumes against job criteria, calculates objective match scores (0-100), and drafts screening invite emails.',
      prompt: 'I need an AI Technical Recruiter to review incoming software engineer resumes against our Senior Fullstack Engineer criteria, calculate an objective score from 0-100, and draft personalized screening invitations.'
    },
    {
      role: 'Competitor Intel Lead',
      dept: 'Marketing',
      icon: '🚀',
      desc: 'Scrapes live web & news via Tavily for competitor feature launches, pricing updates, and crafts viral LinkedIn thought-leadership posts.',
      prompt: 'I need an AI Growth Marketer to monitor breaking AI product releases and funding deals across Google and tech blogs, extract key insights, and draft two high-engagement LinkedIn breakdown posts.'
    },
    {
      role: 'Cashflow & Invoice Guard',
      dept: 'Operations',
      icon: '⚡',
      desc: 'Audits outstanding invoice balances past due, compiles weekly accounts receivable summaries, and drafts firm yet respectful reminders.',
      prompt: 'I need an AI Operations assistant to monitor unpaid client invoices, identify balances past due by more than 5 business days, and draft polite financial reminder emails.'
    }
  ];

  const handleCompile = async () => {
    if (!prompt.trim()) return;
    setIsCompiling(true);
    setCompileStep(1);

    const stepInterval = setInterval(() => {
      setCompileStep((prev) => (prev < 3 ? prev + 1 : prev));
    }, 950);

    try {
      const res = await fetch(`${apiBase}/api/compiler/compile`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt })
      });
      if (res.ok) {
        const data = await res.json();
        setCompiledEmployee(data);
      } else {
        alert('Compilation failed. Please check backend server.');
      }
    } catch {
      alert('Error connecting to compiler backend.');
    } finally {
      clearInterval(stepInterval);
      setIsCompiling(false);
      setCompileStep(0);
    }
  };

  const handleConfirmHire = async () => {
    if (!compiledEmployee) return;
    try {
      const res = await fetch(`${apiBase}/api/employees`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(compiledEmployee)
      });
      if (res.ok) {
        onEmployeeHired(compiledEmployee);
        setCompiledEmployee(null);
        setPrompt('');
      }
    } catch {
      alert('Failed to save hired employee.');
    }
  };

  return (
    <div id="tour-hire" className="space-y-8 max-w-5xl mx-auto">
      {/* Studio Header */}
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4 border-b border-white/[0.08] pb-6">
        <div>
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-300 text-[11px] font-semibold mb-2">
            <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
            <span>Autonomous Employee Compiler</span>
          </div>
          <h2 className="text-2xl font-black text-white tracking-tight">Hire Studio</h2>
          <p className="text-xs text-zinc-400 mt-1">
            Prompt your vision in plain English. The Meta-Agent synthesizes the identity, 5 SOPs, live tools, and safety guardrails.
          </p>
        </div>

        <div className="flex items-center gap-2 bg-white/[0.03] border border-white/[0.08] px-3 py-1.5 rounded-xl text-xs text-zinc-400">
          <Zap className="w-3.5 h-3.5 text-amber-400" />
          <span>Model: <strong className="text-zinc-200">Gemini 3.6 Flash</strong></span>
        </div>
      </div>

      {/* Main Command Input Box */}
      <div className="relative rounded-2xl border border-white/[0.12] bg-[#0c0f17]/90 p-5 shadow-2xl focus-within:border-indigo-500/80 focus-within:ring-2 focus-within:ring-indigo-500/20 transition group">
        <textarea
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          onKeyDown={(e) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
              handleCompile();
            }
          }}
          placeholder="Describe the employee you want to build... (e.g. 'I need an AI recruiter that reads applicant resumes, checks our job requirements, scores them, and drafts Calendly interview links...')"
          rows={4}
          className="w-full bg-transparent text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none resize-none leading-relaxed"
        />

        <div className="flex items-center justify-between pt-4 border-t border-white/[0.06] mt-2">
          <div className="flex items-center gap-2 text-[11px] text-zinc-500">
            <kbd className="px-1.5 py-0.5 rounded bg-white/[0.06] border border-white/[0.1] font-mono text-[10px] text-zinc-400">
              Ctrl + Enter
            </kbd>
            <span>to compile</span>
          </div>

          <button
            type="button"
            onClick={handleCompile}
            disabled={isCompiling || !prompt.trim()}
            className="flex items-center gap-2 px-5 py-2 rounded-xl bg-gradient-to-r from-indigo-600 via-indigo-500 to-violet-600 hover:from-indigo-500 hover:to-violet-500 disabled:opacity-40 disabled:cursor-not-allowed font-semibold text-xs text-white shadow-lg shadow-indigo-600/30 transition active:scale-95 cursor-pointer"
          >
            {isCompiling ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                <span>Compiling Employee...</span>
              </>
            ) : (
              <>
                <Sparkles className="w-3.5 h-3.5" />
                <span>Synthesize Spec</span>
              </>
            )}
          </button>
        </div>

        {/* Step-by-Step Compilation Progress */}
        {isCompiling && (
          <div className="mt-4 p-3.5 rounded-xl bg-indigo-950/40 border border-indigo-500/30 text-xs text-indigo-200 flex items-center gap-3 animate-in fade-in">
            <div className="flex gap-1.5">
              <span className={`w-2 h-2 rounded-full ${compileStep >= 1 ? 'bg-indigo-400 animate-pulse' : 'bg-zinc-700'}`} />
              <span className={`w-2 h-2 rounded-full ${compileStep >= 2 ? 'bg-indigo-400 animate-pulse' : 'bg-zinc-700'}`} />
              <span className={`w-2 h-2 rounded-full ${compileStep >= 3 ? 'bg-indigo-400 animate-pulse' : 'bg-zinc-700'}`} />
            </div>
            <span className="font-medium">
              {compileStep === 1 && 'Phase 1/3: Analyzing objective and determining organizational persona...'}
              {compileStep === 2 && 'Phase 2/3: Formulating 5 Standard Operating Procedures (SOPs)...'}
              {compileStep >= 3 && 'Phase 3/3: Binding live tools (Tavily, Gmail) and safety gates...'}
            </span>
          </div>
        )}
      </div>

      {/* Blueprints / Presets Grid */}
      <div className="space-y-3">
        <div className="text-xs font-bold uppercase tracking-wider text-zinc-400">
          Or Select a Production-Ready Blueprint
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3.5">
          {blueprints.map((b, i) => (
            <div
              key={i}
              onClick={() => setPrompt(b.prompt)}
              className="p-4 rounded-xl bg-white/[0.02] border border-white/[0.06] hover:border-indigo-500/40 hover:bg-white/[0.04] transition cursor-pointer group space-y-2 flex flex-col justify-between"
            >
              <div>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="text-xl">{b.icon}</span>
                    <span className="text-sm font-bold text-zinc-200 group-hover:text-indigo-300 transition">
                      {b.role}
                    </span>
                  </div>
                  <span className="text-[9px] uppercase font-bold px-2 py-0.5 rounded bg-white/[0.06] text-zinc-400 border border-white/[0.06]">
                    {b.dept}
                  </span>
                </div>
                <p className="text-xs text-zinc-400 leading-relaxed mt-2">{b.desc}</p>
              </div>
              <div className="pt-2 flex items-center justify-end text-[11px] font-semibold text-indigo-400 group-hover:translate-x-0.5 transition">
                <span>Load Blueprint</span>
                <ArrowRight className="w-3 h-3 ml-1" />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* COMPILED EMPLOYEE DOSSIER */}
      {compiledEmployee && (
        <div className="mt-8 pt-8 border-t border-white/[0.1] animate-in fade-in slide-in-from-top-6 duration-300">
          <div className="rounded-3xl border border-indigo-500/40 bg-gradient-to-b from-[#0e121c] to-[#07090e] p-6 md:p-8 space-y-6 shadow-2xl ring-1 ring-indigo-500/20">
            {/* Header / ID Badge */}
            <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4 pb-6 border-b border-white/[0.08]">
              <div className="flex items-center gap-4">
                <div className="w-16 h-16 rounded-2xl bg-indigo-950/80 border border-indigo-500/40 flex items-center justify-center text-4xl shadow-inner ring-1 ring-white/10">
                  {compiledEmployee.avatar_emoji || '🤖'}
                </div>
                <div>
                  <div className="flex items-center gap-2.5">
                    <h3 className="text-xl font-black text-white">{compiledEmployee.name}</h3>
                    <span className="text-[10px] font-bold uppercase tracking-wider px-2.5 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                      {compiledEmployee.department}
                    </span>
                  </div>
                  <p className="text-xs font-semibold text-indigo-400 mt-0.5">{compiledEmployee.role}</p>
                </div>
              </div>

              <div className="flex items-center gap-2.5">
                <button
                  type="button"
                  onClick={() => setCompiledEmployee(null)}
                  className="px-4 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] transition cursor-pointer"
                >
                  Discard Spec
                </button>
                <button
                  type="button"
                  onClick={handleConfirmHire}
                  className="flex items-center gap-2 px-5 py-2 rounded-xl text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-600/20 transition active:scale-95 cursor-pointer"
                >
                  <Check className="w-4 h-4" />
                  <span>Hire into Roster</span>
                </button>
              </div>
            </div>

            {/* Core Mission & Behavioral Persona */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4 text-xs">
              <div className="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-1.5">
                <span className="font-bold text-zinc-500 uppercase tracking-wider text-[10px]">Objective & Mandate</span>
                <p className="text-zinc-200 leading-relaxed">{compiledEmployee.objective}</p>
              </div>
              <div className="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-1.5">
                <span className="font-bold text-zinc-500 uppercase tracking-wider text-[10px]">Persona & Guidelines</span>
                <p className="text-zinc-200 leading-relaxed">{compiledEmployee.persona}</p>
              </div>
            </div>

            {/* Synthesized SOPs */}
            <div className="space-y-2">
              <span className="font-bold text-zinc-400 uppercase tracking-wider text-[10px]">
                Standard Operating Procedures (5 SOPs)
              </span>
              <div className="p-4 rounded-xl bg-black/40 border border-white/[0.06] space-y-2">
                {compiledEmployee.sops.map((sop, i) => (
                  <div key={i} className="text-xs text-zinc-300 flex items-start gap-2.5">
                    <span className="text-indigo-400 font-extrabold">•</span>
                    <span>{sop}</span>
                  </div>
                ))}
              </div>
            </div>

            {/* Tool Bindings & Safety Approvals */}
            <div className="flex flex-wrap items-center justify-between gap-4 pt-4 border-t border-white/[0.06]">
              <div className="flex items-center gap-2">
                <span className="text-xs text-zinc-400 font-semibold">Enabled Tools:</span>
                <div className="flex gap-1.5 flex-wrap">
                  {compiledEmployee.tools.map((t) => (
                    <span key={t} className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.06] text-zinc-300 border border-white/[0.1]">
                      {t}
                    </span>
                  ))}
                </div>
              </div>

              {compiledEmployee.requires_approval_for.length > 0 && (
                <div className="flex items-center gap-2 text-xs text-amber-300 bg-amber-500/10 px-3 py-1 rounded-lg border border-amber-500/20">
                  <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
                  <span>Founder sign-off required: {compiledEmployee.requires_approval_for.join(', ')}</span>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
