'use client';

import React, { useState } from 'react';
import {
  Globe,
  Mail,
  Zap,
  Check,
  ExternalLink,
  ShieldAlert,
  Server,
  Cpu
} from 'lucide-react';
import { SettingsState } from '@/types';

interface SettingsViewProps {
  settings: SettingsState;
  onSave: (payload: { tavily_api_key?: string; groq_api_key?: string; smtp_user?: string; smtp_pass?: string; blacklist_domains?: string }) => Promise<void>;
  apiBase?: string;
  onUpdateApiBase?: (url: string) => void;
}

export default function SettingsView({ settings, onSave, apiBase = 'http://127.0.0.1:8000', onUpdateApiBase }: SettingsViewProps) {
  const [tavilyKey, setTavilyKey] = useState('');
  const [groqKey, setGroqKey] = useState('');
  const [smtpPass, setSmtpPass] = useState('');
  const [blacklistInput, setBlacklistInput] = useState(settings.blacklist_domains || 'investor.com,board.com,vip.com,internal.com');
  const [endpointInput, setEndpointInput] = useState(apiBase);
  const [isSaving, setIsSaving] = useState(false);
  const [savedSuccess, setSavedSuccess] = useState(false);
  const [endpointSaved, setEndpointSaved] = useState(false);

  const handleSave = async () => {
    setIsSaving(true);
    const payload: { tavily_api_key?: string; groq_api_key?: string; smtp_user?: string; smtp_pass?: string; blacklist_domains?: string } = {};
    if (tavilyKey.trim()) payload.tavily_api_key = tavilyKey.trim();
    if (groqKey.trim()) payload.groq_api_key = groqKey.trim();
    if (smtpPass.trim()) {
      payload.smtp_user = 'webshastraa@gmail.com';
      payload.smtp_pass = smtpPass.trim();
    }
    if (blacklistInput.trim() !== settings.blacklist_domains) {
      payload.blacklist_domains = blacklistInput.trim();
    }
    await onSave(payload);
    setIsSaving(false);
    setSavedSuccess(true);
    setTimeout(() => setSavedSuccess(false), 3000);
    setTavilyKey('');
    setGroqKey('');
    setSmtpPass('');
  };

  const handleSaveEndpoint = () => {
    if (!endpointInput.trim()) return;
    const cleanUrl = endpointInput.trim().replace(/\/+$/, '');
    if (onUpdateApiBase) {
      onUpdateApiBase(cleanUrl);
    }
    setEndpointSaved(true);
    setTimeout(() => setEndpointSaved(false), 3000);
  };

  return (
    <div id="tour-settings" className="space-y-8 max-w-4xl mx-auto">
      {/* Header */}
      <div className="border-b border-white/[0.08] pb-5">
        <h2 className="text-2xl font-black text-white tracking-tight">Integrations & API Hub</h2>
        <p className="text-xs text-zinc-400 mt-1">
          Manage your LLM reasoning, live web intelligence, and outbound communication transports
        </p>
      </div>

      <div className="grid grid-cols-1 gap-6">
        {/* Backend Engine API Endpoint Card */}
        <div className="rounded-2xl border border-violet-500/20 bg-[#0a0d14]/80 p-6 space-y-4 shadow-xl">
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-violet-500/10 border border-violet-500/20 flex items-center justify-center text-violet-400 shrink-0">
                <Server className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  Engine API Endpoint
                </h3>
                <p className="text-xs text-zinc-400">
                  Target FastAPI backend (Render, Railway, Cloudflare tunnel, or local server)
                </p>
              </div>
            </div>
            <span className="px-2.5 py-1 rounded-full text-[10px] font-mono font-bold bg-violet-500/10 text-violet-300 border border-violet-500/30 self-start">
              {apiBase}
            </span>
          </div>

          <div className="space-y-3 pt-1">
            <div className="flex flex-col sm:flex-row gap-2">
              <input
                type="text"
                value={endpointInput}
                onChange={(e) => setEndpointInput(e.target.value)}
                placeholder="e.g. https://webshastraa-api.onrender.com or https://xxxx.trycloudflare.com"
                className="flex-1 px-3 py-2 text-xs rounded-xl bg-black/40 border border-white/[0.08] text-white focus:outline-none focus:border-violet-500 font-mono"
              />
              <button
                type="button"
                onClick={handleSaveEndpoint}
                className="px-4 py-2 text-xs font-bold rounded-xl bg-violet-600 hover:bg-violet-500 text-white transition cursor-pointer flex items-center justify-center gap-1.5 shrink-0"
              >
                {endpointSaved ? (
                  <>
                    <Check className="w-3.5 h-3.5" />
                    <span>Saved!</span>
                  </>
                ) : (
                  <span>Update Endpoint</span>
                )}
              </button>
            </div>
            <p className="text-[11px] text-zinc-500">
              When accessing Webshastraa AI on mobile devices or outside your local network, enter your public backend URL or tunnel address here.
            </p>
          </div>
        </div>

        {/* Groq High-Speed LPU Card */}
        <div className="rounded-2xl border border-amber-500/20 bg-[#0a0d14]/80 p-6 space-y-4 shadow-xl">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                <Cpu className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white flex items-center gap-2">
                  Groq High-Speed LPU Engine
                  <span className="text-[10px] px-2 py-0.5 rounded-full bg-amber-500/20 text-amber-300 font-mono">0.5s Latency</span>
                </h3>
                <p className="text-xs text-zinc-400">Ultra-fast inference (14,400 daily requests) with automatic Gemini fallback</p>
              </div>
            </div>
            <span
              className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${
                settings.groq_connected
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-zinc-800 text-zinc-400 border-zinc-700'
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${settings.groq_connected ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
              {settings.groq_connected ? 'Active & High-Speed' : 'Not Configured'}
            </span>
          </div>

          <div className="rounded-xl bg-black/30 p-4 border border-white/[0.04] text-xs space-y-3">
            <div className="flex items-center justify-between text-zinc-300">
              <span>Active Groq Key:</span>
              <span className="font-mono text-amber-400 font-bold">
                {settings.groq_connected ? `Verified (${settings.groq_key_preview || 'gsk_...'})` : 'None (Using Gemini)'}
              </span>
            </div>
            <div className="flex items-center justify-between text-zinc-400 text-[11px] pt-2 border-t border-white/[0.06]">
              <span>Get your free Groq API key (instant setup)</span>
              <a
                href="https://console.groq.com/keys"
                target="_blank"
                rel="noreferrer"
                className="text-amber-400 hover:text-amber-300 flex items-center gap-1 font-medium transition"
              >
                console.groq.com <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>

          <div className="space-y-1.5 pt-1">
            <label className="text-xs font-semibold text-zinc-300">Update Groq API Key</label>
            <input
              type="password"
              value={groqKey}
              onChange={(e) => setGroqKey(e.target.value)}
              placeholder="gsk_..."
              className="w-full px-3 py-2 text-xs rounded-xl bg-black/40 border border-white/[0.08] text-white focus:outline-none focus:border-amber-500 font-mono"
            />
          </div>
        </div>

        {/* Gemini Engine Card */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0d14]/80 p-6 space-y-4 shadow-xl">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-indigo-500/10 border border-indigo-500/20 flex items-center justify-center text-indigo-400">
                <Zap className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Google Gemini 3.6 Flash</h3>
                <p className="text-xs text-zinc-400">Primary reasoning model & Prompt-to-SOP compiler</p>
              </div>
            </div>
            <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Online & Authenticated
            </span>
          </div>
          <div className="text-xs text-zinc-400 bg-black/30 p-3 rounded-xl border border-white/[0.04] flex items-center justify-between font-mono">
            <span>Project ID: 131356690224</span>
            <span className="text-emerald-400">Low-latency streaming active</span>
          </div>
        </div>

        {/* Tavily AI Search Card */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0d14]/80 p-6 space-y-5 shadow-xl">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-purple-500/10 border border-purple-500/20 flex items-center justify-center text-purple-400">
                <Globe className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Tavily AI Search Engine</h3>
                <p className="text-xs text-zinc-400">Real-time web research, company intelligence & content extraction</p>
              </div>
            </div>
            <span
              className={`flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border ${
                settings.tavily_connected
                  ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20'
                  : 'bg-zinc-800 text-zinc-400 border-zinc-700'
              }`}
            >
              <span className={`w-2 h-2 rounded-full ${settings.tavily_connected ? 'bg-emerald-400' : 'bg-zinc-500'}`} />
              {settings.tavily_connected ? 'Connected' : 'Not Connected'}
            </span>
          </div>

          <div className="rounded-xl bg-black/30 p-4 border border-white/[0.04] text-xs space-y-3">
            <div className="flex items-center justify-between text-zinc-300">
              <span>Active Key Status:</span>
              <span className="font-mono text-emerald-400 font-bold">
                {settings.tavily_connected ? `Verified (${settings.tavily_key_preview})` : 'Missing'}
              </span>
            </div>
            <div className="flex items-center justify-between text-zinc-400 text-[11px] pt-2 border-t border-white/[0.06]">
              <span>Need key updates or extra quotas?</span>
              <a
                href="https://app.tavily.com"
                target="_blank"
                rel="noreferrer"
                className="text-indigo-400 hover:text-indigo-300 font-semibold flex items-center gap-1"
              >
                Open app.tavily.com <ExternalLink className="w-3 h-3" />
              </a>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-300">Update Tavily API Key</label>
            <input
              type="password"
              value={tavilyKey}
              onChange={(e) => setTavilyKey(e.target.value)}
              placeholder="Paste new key (tvly-...)"
              className="w-full text-xs rounded-xl bg-black/40 border border-white/[0.08] px-3.5 py-2.5 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-indigo-500"
            />
          </div>
        </div>

        {/* Gmail SMTP Card */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0d14]/80 p-6 space-y-5 shadow-xl">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400">
                <Mail className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">Gmail SMTP Transport Server</h3>
                <p className="text-xs text-zinc-400">Dispatches real emails to prospects upon founder authorization</p>
              </div>
            </div>
            <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              SMTP Ready (465 SSL)
            </span>
          </div>

          <div className="rounded-xl bg-black/30 p-4 border border-white/[0.04] text-xs space-y-2.5">
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Designated Sender:</span>
              <span className="font-mono text-zinc-200 font-bold">webshastraa@gmail.com</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Currently Active Transport:</span>
              <span className="font-mono text-emerald-400 font-bold">{settings.active_email_sender}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-zinc-400">Server Host & Port:</span>
              <span className="font-mono text-zinc-300">smtp.gmail.com:465</span>
            </div>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-300">Google App Password for webshastraa@gmail.com</label>
            <input
              type="password"
              value={smtpPass}
              onChange={(e) => setSmtpPass(e.target.value)}
              placeholder="16-character Google App Password (e.g. zken zvuk xpcq uqfc)"
              className="w-full text-xs rounded-xl bg-black/40 border border-white/[0.08] px-3.5 py-2.5 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-indigo-500"
            />
            <p className="text-[11px] text-zinc-500 pt-1">
              Generate an App Password at <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noreferrer" className="text-indigo-400 underline">myaccount.google.com/apppasswords</a>. Until configured, emails dispatch via the verified Indrani Jewellers transport backup.
            </p>
          </div>
        </div>

        {/* VIP Domain Blacklist Guardrail Card */}
        <div className="rounded-2xl border border-white/[0.08] bg-[#0a0d14]/80 p-6 space-y-4 shadow-xl">
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
                <ShieldAlert className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">VIP & Internal Outreach Blacklist</h3>
                <p className="text-xs text-zinc-400">Hard stop guardrail: AI employees can never contact these domains</p>
              </div>
            </div>
            <span className="flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-2 h-2 rounded-full bg-emerald-400" />
              Active Protection
            </span>
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-semibold text-zinc-300">Restricted Domains & Keywords (comma-separated)</label>
            <input
              type="text"
              value={blacklistInput}
              onChange={(e) => setBlacklistInput(e.target.value)}
              placeholder="investor.com, board.com, keyclient.com, internal.com"
              className="w-full text-xs rounded-xl bg-black/40 border border-white/[0.08] px-3.5 py-2.5 text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-rose-500 font-mono"
            />
            <p className="text-[11px] text-zinc-500 pt-1">
              Any email address or domain matching these patterns will be automatically blocked before transmission, protecting executive and investor relations.
            </p>
          </div>
        </div>

        {/* Save Bar */}
        <div className="flex items-center justify-between pt-2">
          {savedSuccess && (
            <span className="text-xs font-semibold text-emerald-400 flex items-center gap-1.5">
              <Check className="w-4 h-4" /> Integrations updated successfully!
            </span>
          )}
          <div className="flex-1" />
          <button
            type="button"
            onClick={handleSave}
            disabled={isSaving || (!tavilyKey.trim() && !smtpPass.trim())}
            className="px-6 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-40 disabled:cursor-not-allowed text-xs font-bold text-white shadow-lg shadow-indigo-600/20 transition active:scale-95 cursor-pointer"
          >
            {isSaving ? 'Saving...' : 'Save Integrations'}
          </button>
        </div>
      </div>
    </div>
  );
}
