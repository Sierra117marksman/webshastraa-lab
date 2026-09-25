'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { Shield, ShieldCheck, ChevronDown, Info } from 'lucide-react';
import { ToolPermission, PermissionScope } from '@/types';

interface PermissionPanelProps {
  employeeId: string;
  apiBase: string;
  employeeTools: string[];
}

const TOOL_EMOJI: Record<string, string> = {
  web_search: '🔍',
  email_sender: '📧',
  sheet_logger: '📊',
  slack_notifier: '💬'
};

const SCOPE_META: Record<PermissionScope, { label: string; color: string }> = {
  READ: { label: 'READ', color: 'bg-zinc-500/20 text-zinc-300 border-zinc-500/30' },
  ANALYZE: { label: 'ANALYZE', color: 'bg-blue-500/20 text-blue-300 border-blue-500/30' },
  DRAFT: { label: 'DRAFT', color: 'bg-yellow-500/20 text-yellow-300 border-yellow-500/30' },
  REQUEST: { label: 'REQUEST', color: 'bg-orange-500/20 text-orange-300 border-orange-500/30' },
  EXECUTE: { label: 'EXECUTE', color: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30' }
};

const ALL_SCOPES: PermissionScope[] = ['READ', 'ANALYZE', 'DRAFT', 'REQUEST', 'EXECUTE'];

function getToolEmoji(toolId: string): string {
  const key = Object.keys(TOOL_EMOJI).find((k) => toolId.toLowerCase().includes(k));
  return key ? TOOL_EMOJI[key] : '⚙️';
}

function getToolLabel(toolId: string): string {
  return toolId
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function PermissionPanel({ employeeId, apiBase, employeeTools }: PermissionPanelProps) {
  const [permissions, setPermissions] = useState<ToolPermission[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingTool, setEditingTool] = useState<string | null>(null);
  const [editState, setEditState] = useState<{ permission: PermissionScope; requires_approval: boolean } | null>(null);
  const [saving, setSaving] = useState(false);

  const fetchPermissions = useCallback(async () => {
    try {
      const res = await fetch(`${apiBase}/api/employees/${employeeId}/permissions`);
      if (res.ok) {
        const data: ToolPermission[] = await res.json();
        setPermissions(data);
      }
    } catch {
      // Ignore transient network hiccups
    } finally {
      setLoading(false);
    }
  }, [apiBase, employeeId]);

  useEffect(() => {
    fetchPermissions();
  }, [fetchPermissions]);

  const getPermissionForTool = (toolId: string): ToolPermission => {
    return (
      permissions.find((p) => p.tool_id === toolId) ?? {
        tool_id: toolId,
        permission: 'READ',
        requires_approval: false,
        notes: null
      }
    );
  };

  const startEdit = (toolId: string) => {
    const p = getPermissionForTool(toolId);
    setEditingTool(toolId);
    setEditState({ permission: p.permission, requires_approval: p.requires_approval });
  };

  const cancelEdit = () => {
    setEditingTool(null);
    setEditState(null);
  };

  const savePermission = async (toolId: string) => {
    if (!editState) return;
    setSaving(true);
    try {
      const body: ToolPermission = {
        tool_id: toolId,
        permission: editState.permission,
        requires_approval: editState.requires_approval
      };
      const res = await fetch(`${apiBase}/api/employees/${employeeId}/permissions/${toolId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });
      if (res.ok) {
        await fetchPermissions();
        cancelEdit();
      }
    } catch {
      // Ignore transient network hiccups
    } finally {
      setSaving(false);
    }
  };

  const toolList = employeeTools.length > 0
    ? employeeTools
    : permissions.map((p) => p.tool_id);

  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-12 rounded-xl bg-white/[0.03] border border-white/[0.06] animate-pulse" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2">
        <Shield className="w-4 h-4 text-indigo-400" />
        <span className="text-sm font-semibold text-zinc-200">Tool Permissions</span>
      </div>

      <div className="space-y-2">
        {toolList.map((toolId) => {
          const perm = getPermissionForTool(toolId);
          const meta = SCOPE_META[perm.permission] ?? SCOPE_META.READ;
          const isEditing = editingTool === toolId;

          return (
            <div
              key={toolId}
              className="rounded-xl border border-white/[0.06] bg-white/[0.03] p-3 space-y-2"
            >
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5 min-w-0">
                  <span className="text-lg">{getToolEmoji(toolId)}</span>
                  <div className="min-w-0">
                    <p className="text-xs font-semibold text-zinc-200 truncate">{getToolLabel(toolId)}</p>
                    {perm.notes && (
                      <p className="text-[10px] text-zinc-500 truncate">{perm.notes}</p>
                    )}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  {perm.requires_approval && (
                    <span title="Requires approval">
                      <ShieldCheck className="w-3.5 h-3.5 text-amber-400" />
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => isEditing ? cancelEdit() : startEdit(toolId)}
                    className={`flex items-center gap-1 px-2 py-1 rounded-lg text-[10px] font-semibold border transition ${meta.color} hover:opacity-80`}
                  >
                    {meta.label}
                    <ChevronDown className={`w-3 h-3 transition ${isEditing ? 'rotate-180' : ''}`} />
                  </button>
                </div>
              </div>

              {isEditing && editState && (
                <div className="pt-2 border-t border-white/[0.06] space-y-3">
                  <div>
                    <p className="text-[10px] text-zinc-500 mb-1.5 uppercase tracking-wider">Permission Level</p>
                    <div className="flex flex-wrap gap-1.5">
                      {ALL_SCOPES.map((scope) => {
                        const sm = SCOPE_META[scope];
                        const isSelected = editState.permission === scope;
                        return (
                          <button
                            key={scope}
                            type="button"
                            onClick={() => setEditState((s) => s ? { ...s, permission: scope } : s)}
                            className={`px-2.5 py-1 rounded-lg text-[10px] font-semibold border transition ${sm.color} ${
                              isSelected ? 'ring-1 ring-white/30 opacity-100' : 'opacity-50 hover:opacity-75'
                            }`}
                          >
                            {sm.label}
                          </button>
                        );
                      })}
                    </div>
                  </div>

                  <div className="flex items-center justify-between">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <div
                        onClick={() => setEditState((s) => s ? { ...s, requires_approval: !s.requires_approval } : s)}
                        className={`w-8 h-4 rounded-full transition relative ${
                          editState.requires_approval ? 'bg-amber-500' : 'bg-zinc-700'
                        }`}
                      >
                        <span
                          className={`absolute top-0.5 w-3 h-3 rounded-full bg-white shadow transition-all ${
                            editState.requires_approval ? 'left-4.5' : 'left-0.5'
                          }`}
                          style={{ left: editState.requires_approval ? '18px' : '2px' }}
                        />
                      </div>
                      <span className="text-xs text-zinc-400">Requires Approval</span>
                    </label>

                    <div className="flex gap-2">
                      <button
                        type="button"
                        onClick={cancelEdit}
                        className="px-2.5 py-1 rounded-lg text-[10px] font-semibold text-zinc-400 hover:text-zinc-200 bg-white/[0.04] transition"
                      >
                        Cancel
                      </button>
                      <button
                        type="button"
                        disabled={saving}
                        onClick={() => savePermission(toolId)}
                        className="px-3 py-1 rounded-lg text-[10px] font-semibold text-white bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 transition"
                      >
                        {saving ? 'Saving...' : 'Save'}
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center gap-1.5 text-[10px] text-zinc-600">
        <Info className="w-3 h-3" />
        <span>Changes take effect on next task dispatch.</span>
      </div>
    </div>
  );
}
