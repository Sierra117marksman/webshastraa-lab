'use client';

import React, { useState, useEffect, useCallback } from 'react';
import {
  Brain,
  Plus,
  Star,
  Trash2,
  Check,
  X,
  ChevronDown,
  ChevronUp,
  AlertTriangle,
  Pencil,
  ToggleLeft,
  Lightbulb
} from 'lucide-react';
import { MemoryRecord, MemoryCategory, MemoryStatus } from '@/types';

interface MemoryVaultProps {
  employeeId: string;
  apiBase: string;
}

const CATEGORY_META: Record<MemoryCategory, { label: string; color: string }> = {
  mistake_avoided: { label: 'Mistake Avoided', color: 'bg-red-500/20 text-red-300 border-red-500/30' },
  learned_rule: { label: 'Learned Rule', color: 'bg-blue-500/20 text-blue-300 border-blue-500/30' },
  proven_playbook: { label: 'Proven Playbook', color: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' },
  founder_preference: { label: 'Founder Preference', color: 'bg-purple-500/20 text-purple-300 border-purple-500/30' }
};

function ConfidenceBar({ score }: { score: number }) {
  const pct = Math.round(score * 100);
  const color = pct >= 80 ? 'bg-emerald-400' : pct >= 50 ? 'bg-amber-400' : 'bg-red-400';
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1 rounded-full bg-white/[0.08] overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-[10px] text-zinc-500 font-mono w-6 text-right">{pct}%</span>
    </div>
  );
}

function PriorityStars({ priority }: { priority: number }) {
  return (
    <div className="flex gap-0.5">
      {[1, 2, 3, 4, 5].map((i) => (
        <Star
          key={i}
          className={`w-3 h-3 ${i <= priority ? 'text-amber-400 fill-amber-400' : 'text-zinc-700'}`}
        />
      ))}
    </div>
  );
}

interface AddFormState {
  title: string;
  category: MemoryCategory;
  scope: string;
  context: string;
  critique: string;
  distilled_rule: string;
  priority: number;
}

const EMPTY_FORM: AddFormState = {
  title: '',
  category: 'learned_rule',
  scope: 'global',
  context: '',
  critique: '',
  distilled_rule: '',
  priority: 3
};

export default function MemoryVault({ employeeId, apiBase }: MemoryVaultProps) {
  const [memories, setMemories] = useState<MemoryRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState<AddFormState>(EMPTY_FORM);
  const [submitting, setSubmitting] = useState(false);
  const [conflictId, setConflictId] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editText, setEditText] = useState('');
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const fetchMemories = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/employees/${employeeId}/memories?status=all`);
      if (res.ok) setMemories(await res.json());
    } catch {
      // Ignore transient network hiccups
    } finally {
      setLoading(false);
    }
  }, [apiBase, employeeId]);

  useEffect(() => {
    fetchMemories();
  }, [fetchMemories]);

  const patchMemory = async (id: string, patch: Partial<Pick<MemoryRecord, 'status' | 'distilled_rule'>>) => {
    try {
      const res = await fetch(`${apiBase}/api/memories/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(patch)
      });
      if (res.ok) fetchMemories();
    } catch {
      // Ignore transient network hiccups
    }
  };

  const deleteMemory = async (id: string) => {
    if (!confirm('Delete this memory rule permanently?')) return;
    try {
      await fetch(`${apiBase}/api/memories/${id}`, { method: 'DELETE' });
      fetchMemories();
    } catch {
      // Ignore transient network hiccups
    }
  };

  const handleAddSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitting(true);
    setConflictId(null);
    try {
      const res = await fetch(`${apiBase}/api/employees/${employeeId}/memories`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...form, source: 'founder_manual' })
      });
      if (res.ok) {
        const created: MemoryRecord = await res.json();
        if (created.status === 'proposed') setConflictId(created.id);
        setForm(EMPTY_FORM);
        setShowForm(false);
        fetchMemories();
      }
    } catch {
      // Ignore transient network hiccups
    } finally {
      setSubmitting(false);
    }
  };

  const saveEdit = async (id: string) => {
    await patchMemory(id, { distilled_rule: editText });
    setEditingId(null);
  };

  const active = memories.filter((m) => m.status === 'active');
  const proposed = memories.filter((m) => m.status === 'proposed');

  const MemoryCard = ({ mem, isProposed }: { mem: MemoryRecord; isProposed: boolean }) => {
    const meta = CATEGORY_META[mem.category] ?? CATEGORY_META.learned_rule;
    const isExpanded = expandedId === mem.id;
    const isEditing = editingId === mem.id;

    return (
      <div
        className={`rounded-xl border bg-white/[0.03] p-4 space-y-3 transition ${
          isProposed ? 'border-amber-500/20' : 'border-white/[0.06]'
        } ${conflictId === mem.id ? 'ring-1 ring-amber-500/40' : ''}`}
      >
        {conflictId === mem.id && (
          <div className="flex items-start gap-2 text-xs text-amber-300 bg-amber-500/10 border border-amber-500/20 rounded-lg p-2.5">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
            <span>This rule conflicts with an existing active rule. Approve to supersede it.</span>
          </div>
        )}

        <div className="flex items-start justify-between gap-2">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap mb-1">
              <span className={`text-[10px] font-semibold px-2 py-0.5 rounded border ${meta.color}`}>
                {meta.label}
              </span>
              <span className="text-[10px] text-zinc-500 bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06]">
                {mem.scope}
              </span>
              <span className="text-[10px] text-zinc-600 font-mono">v{mem.version}</span>
            </div>
            <p className="text-sm font-semibold text-zinc-200 truncate">{mem.title}</p>
          </div>
          <button
            type="button"
            onClick={() => setExpandedId(isExpanded ? null : mem.id)}
            className="p-1 rounded text-zinc-600 hover:text-zinc-300 transition shrink-0"
          >
            {isExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>
        </div>

        {isEditing ? (
          <div className="space-y-2">
            <textarea
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              rows={3}
              className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50 resize-none"
            />
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => saveEdit(mem.id)}
                className="flex items-center gap-1 px-3 py-1.5 rounded-lg text-xs font-semibold text-white bg-indigo-600/80 hover:bg-indigo-600 transition"
              >
                <Check className="w-3 h-3" /> Save
              </button>
              <button
                type="button"
                onClick={() => setEditingId(null)}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-400 hover:text-zinc-200 bg-white/[0.04] transition"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <p className="text-xs text-zinc-400 leading-relaxed bg-white/[0.02] p-2.5 rounded-lg border border-white/[0.04]">
            {mem.distilled_rule}
          </p>
        )}

        {isExpanded && !isEditing && (
          <div className="space-y-2 pt-1 border-t border-white/[0.06]">
            {mem.critique && (
              <div>
                <p className="text-[10px] text-zinc-500 uppercase tracking-wider mb-1">Critique</p>
                <p className="text-xs text-zinc-400">{mem.critique}</p>
              </div>
            )}
            <div className="text-[10px] text-zinc-500">Source: {mem.source}</div>
          </div>
        )}

        <div className="flex items-center justify-between gap-3">
          <div className="flex-1 space-y-1">
            <PriorityStars priority={mem.priority} />
            <ConfidenceBar score={mem.confidence_score} />
          </div>

          {isProposed ? (
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={() => patchMemory(mem.id, { status: 'active' as MemoryStatus })}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-emerald-300 bg-emerald-500/10 border border-emerald-500/20 hover:bg-emerald-500/20 transition"
              >
                <Check className="w-3 h-3" /> Approve
              </button>
              <button
                type="button"
                onClick={() => patchMemory(mem.id, { status: 'rejected' as MemoryStatus })}
                className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold text-red-400 bg-red-500/10 border border-red-500/20 hover:bg-red-500/20 transition"
              >
                <X className="w-3 h-3" /> Reject
              </button>
            </div>
          ) : (
            <div className="flex items-center gap-1.5 shrink-0">
              <button
                type="button"
                onClick={() => { setEditingId(mem.id); setEditText(mem.distilled_rule); }}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-zinc-200 hover:bg-white/[0.06] transition"
                title="Edit rule text"
              >
                <Pencil className="w-3 h-3" />
              </button>
              <button
                type="button"
                onClick={() => patchMemory(mem.id, { status: 'superseded' as MemoryStatus })}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-amber-300 hover:bg-amber-500/10 transition"
                title="Toggle off (supersede)"
              >
                <ToggleLeft className="w-3.5 h-3.5" />
              </button>
              <button
                type="button"
                onClick={() => deleteMemory(mem.id)}
                className="p-1.5 rounded-lg text-zinc-500 hover:text-red-400 hover:bg-red-500/10 transition"
                title="Delete"
              >
                <Trash2 className="w-3 h-3" />
              </button>
            </div>
          )}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="space-y-3">
        {[1, 2].map((i) => (
          <div key={i} className="h-28 rounded-xl bg-white/[0.03] border border-white/[0.06] animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Brain className="w-4 h-4 text-indigo-400" />
          <span className="text-sm font-semibold text-zinc-200">Memory Vault</span>
          <span className="text-[10px] text-zinc-500 bg-white/[0.04] px-1.5 py-0.5 rounded border border-white/[0.06]">
            {active.length} active
          </span>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold text-indigo-300 bg-indigo-500/10 border border-indigo-500/20 hover:bg-indigo-500/20 transition"
        >
          <Plus className="w-3.5 h-3.5" />
          Add Rule
        </button>
      </div>

      {showForm && (
        <form
          onSubmit={handleAddSubmit}
          className="rounded-xl border border-indigo-500/20 bg-indigo-500/5 p-4 space-y-3"
        >
          <p className="text-xs font-semibold text-indigo-300">New Memory Rule</p>
          <input
            required
            value={form.title}
            onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))}
            placeholder="Rule title"
            className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50"
          />
          <div className="grid grid-cols-2 gap-3">
            <select
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value as MemoryCategory }))}
              className="bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50"
            >
              <option value="learned_rule">Learned Rule</option>
              <option value="mistake_avoided">Mistake Avoided</option>
              <option value="proven_playbook">Proven Playbook</option>
              <option value="founder_preference">Founder Preference</option>
            </select>
            <input
              value={form.scope}
              onChange={(e) => setForm((f) => ({ ...f, scope: e.target.value }))}
              placeholder="Scope (e.g. global)"
              className="bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50"
            />
          </div>
          <textarea
            required
            value={form.context}
            onChange={(e) => setForm((f) => ({ ...f, context: e.target.value }))}
            placeholder="Context — what situation does this apply to?"
            rows={2}
            className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50 resize-none"
          />
          <textarea
            value={form.critique}
            onChange={(e) => setForm((f) => ({ ...f, critique: e.target.value }))}
            placeholder="Critique — what went wrong or could go wrong?"
            rows={2}
            className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50 resize-none"
          />
          <textarea
            required
            value={form.distilled_rule}
            onChange={(e) => setForm((f) => ({ ...f, distilled_rule: e.target.value }))}
            placeholder="Distilled rule — the exact instruction for the AI..."
            rows={2}
            className="w-full bg-white/[0.05] border border-white/[0.1] rounded-lg px-3 py-2 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50 resize-none"
          />
          <div className="flex items-center gap-3">
            <label className="text-xs text-zinc-400">Priority:</label>
            <select
              value={form.priority}
              onChange={(e) => setForm((f) => ({ ...f, priority: Number(e.target.value) }))}
              className="bg-white/[0.05] border border-white/[0.1] rounded-lg px-2 py-1.5 text-xs text-zinc-200 focus:outline-none focus:border-indigo-500/50"
            >
              {[1, 2, 3, 4, 5].map((v) => (
                <option key={v} value={v}>{v}</option>
              ))}
            </select>
            <div className="flex gap-2 ml-auto">
              <button
                type="button"
                onClick={() => { setShowForm(false); setForm(EMPTY_FORM); }}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold text-zinc-400 hover:text-zinc-200 bg-white/[0.04] transition"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="px-4 py-1.5 rounded-lg text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition"
              >
                {submitting ? 'Saving...' : 'Save Rule'}
              </button>
            </div>
          </div>
        </form>
      )}

      {proposed.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Lightbulb className="w-3.5 h-3.5 text-amber-400" />
            <span className="text-xs font-semibold text-amber-300">Proposed — Pending Review</span>
            <span className="text-[10px] bg-amber-500/20 text-amber-300 border border-amber-500/30 px-1.5 py-0.5 rounded">
              {proposed.length}
            </span>
          </div>
          {proposed.map((m) => (
            <MemoryCard key={m.id} mem={m} isProposed />
          ))}
        </div>
      )}

      <div className="space-y-3">
        <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Active Rules</p>
        {active.length === 0 ? (
          <div className="text-center py-8 px-4">
            <Brain className="w-8 h-8 text-zinc-700 mx-auto mb-2" />
            <p className="text-xs text-zinc-500">
              No active rules yet. Dispatch tasks and review rejections to build this employee&apos;s memory.
            </p>
          </div>
        ) : (
          active.map((m) => <MemoryCard key={m.id} mem={m} isProposed={false} />)
        )}
      </div>
    </div>
  );
}
