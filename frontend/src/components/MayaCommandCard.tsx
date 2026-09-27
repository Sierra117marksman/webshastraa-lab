'use client';

import React, { useState } from 'react';
import {
  AlertTriangle,
  Check,
  X,
  ExternalLink,
  ShieldCheck,
  FileSearch,
  Send,
  ChevronDown,
  ChevronUp,
  Loader2,
  Lock
} from 'lucide-react';
import { TaskResearchLedger, ResearchCandidate } from '@/types';

interface MayaCommandCardProps {
  ledger: TaskResearchLedger;
  apiBase: string;
  onApprove: (taskId: string, approved: boolean, feedback?: string) => Promise<void>;
  onRefreshLedger: () => Promise<void>;
}

export default function MayaCommandCard({
  ledger,
  apiBase,
  onApprove,
  onRefreshLedger
}: MayaCommandCardProps) {
  const [openEvidenceId, setOpenEvidenceId] = useState<string | null>(null);
  const [openReviewId, setOpenReviewId] = useState<string | null>(null);
  const [showRejected, setShowRejected] = useState<boolean>(false);
  const [rejectMode, setRejectMode] = useState<boolean>(false);
  const [rejectFeedback, setRejectFeedback] = useState<string>('');
  const [recipientOverrides, setRecipientOverrides] = useState<Record<string, string>>({});
  const [queueingCandidateId, setQueueingCandidateId] = useState<string | null>(null);
  const [approvingState, setApprovingState] = useState<'approving' | 'rejecting' | null>(null);

  const isWorking =
    ledger.task_status === 'running' ||
    ['planning', 'discovering', 'collecting', 'verifying', 'qualifying', 'composing', 'validating'].includes(
      ledger.session_status
    );
  const isWaitingApproval =
    ledger.task_status === 'waiting_approval' || Boolean(ledger.pending_approval?.required);

  const verifiedCandidates = ledger.candidates.filter((c) => c.qualification_status === 'VERIFIED');
  const prospectCandidates = ledger.candidates.filter((c) => c.qualification_status === 'PROSPECT');
  const rejectedCandidates = ledger.candidates.filter((c) => c.qualification_status === 'REJECTED');

  const handleRequestOutreach = async (candidate: ResearchCandidate) => {
    setQueueingCandidateId(candidate.id);
    try {
      const toEmail =
        recipientOverrides[candidate.id]?.trim() ||
        candidate.outreach_draft?.to ||
        `contact@${candidate.canonical_domain}`;
      const res = await fetch(
        `${apiBase}/api/tasks/${ledger.task_id}/candidates/${candidate.id}/request-outreach`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            to: toEmail,
            subject: candidate.outreach_draft?.subject,
            body: candidate.outreach_draft?.body
          })
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Failed to queue outreach' }));
        alert(err.detail || 'Policy Engine blocked outreach request');
        return;
      }
      await onRefreshLedger();
    } catch {
      alert('Network error while requesting outreach approval.');
    } finally {
      setQueueingCandidateId(null);
    }
  };

  const handleApprovalDecision = async (approved: boolean) => {
    setApprovingState(approved ? 'approving' : 'rejecting');
    try {
      await onApprove(
        ledger.task_id,
        approved,
        approved ? undefined : rejectFeedback.trim() || 'Rejected by founder'
      );
      setRejectMode(false);
      setRejectFeedback('');
      await onRefreshLedger();
    } finally {
      setApprovingState(null);
    }
  };

  const renderCandidateCard = (candidate: ResearchCandidate) => {
    const isEvidenceOpen = openEvidenceId === candidate.id;
    const isReviewOpen = openReviewId === candidate.id;
    const isVerified = candidate.qualification_status === 'VERIFIED';
    const isProspect = candidate.qualification_status === 'PROSPECT';

    return (
      <div
        key={candidate.id}
        className={`rounded-2xl border p-4 sm:p-5 space-y-3.5 transition ${
          isVerified
            ? 'border-emerald-500/30 bg-[#091118]/90'
            : isProspect
            ? 'border-amber-500/25 bg-[#0d111a]/90'
            : 'border-white/[0.07] bg-black/40'
        }`}
      >
        {/* Top Row: Brand Name, Canonical Domain, Status Pill */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h4 className="text-base font-black text-white tracking-tight">
                {candidate.company_name}
              </h4>
              <a
                href={candidate.final_url || candidate.initial_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-xs font-mono text-indigo-300 hover:text-indigo-200 underline decoration-indigo-500/40"
              >
                <span>{candidate.canonical_domain}</span>
                <ExternalLink className="w-3 h-3" />
              </a>
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-white/[0.05] text-zinc-400 border border-white/[0.07]">
                Hop {candidate.discovery_hop}
              </span>
              {candidate.http_status && (
                <span
                  className={`text-[10px] font-mono px-2 py-0.5 rounded border ${
                    candidate.http_status === 200
                      ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/25'
                      : 'bg-amber-500/10 text-amber-300 border-amber-500/25'
                  }`}
                >
                  HTTP {candidate.http_status}
                </span>
              )}
            </div>
          </div>

          <span
            className={`self-start sm:self-auto text-[10px] font-extrabold px-2.5 py-1 rounded-full uppercase tracking-wider border ${
              isVerified
                ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40'
                : isProspect
                ? 'bg-amber-500/20 text-amber-300 border-amber-500/40'
                : 'bg-rose-500/20 text-rose-300 border-rose-500/40'
            }`}
          >
            {candidate.qualification_status}
          </span>
        </div>

        {/* Checklist Lines: ✓ Supported, ? Unverified, ✕ Contradicted */}
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5 pt-1">
          {candidate.badges.map((badge, idx) => {
            const isSupported = badge.status === 'SUPPORTED';
            const isContradicted = badge.status === 'CONTRADICTED';
            return (
              <div
                key={`${badge.field}-${idx}`}
                className={`flex items-center gap-2 text-xs font-mono px-2.5 py-1.5 rounded-xl border ${
                  isSupported
                    ? 'bg-emerald-500/[0.07] border-emerald-500/20 text-emerald-200'
                    : isContradicted
                    ? 'bg-rose-500/[0.08] border-rose-500/25 text-rose-200'
                    : 'bg-amber-500/[0.07] border-amber-500/20 text-amber-200'
                }`}
              >
                <span
                  className={`font-black text-sm leading-none ${
                    isSupported
                      ? 'text-emerald-400'
                      : isContradicted
                      ? 'text-rose-400'
                      : 'text-amber-400'
                  }`}
                >
                  {badge.symbol}
                </span>
                <span className="truncate">{badge.label}</span>
              </div>
            );
          })}
        </div>

        {candidate.rejection_reason && (
          <div className="text-xs text-rose-300 bg-rose-950/30 border border-rose-500/25 rounded-xl px-3 py-2 font-mono">
            Rejection reason: {candidate.rejection_reason}
          </div>
        )}

        {/* Footer Strip: Evidence & Claims Counter + [View Evidence] [Review] */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-2 border-t border-white/[0.06]">
          <div className="flex items-center gap-4 text-xs font-mono text-zinc-300">
            <span>
              Evidence: <strong className="text-white">{candidate.evidence_count}</strong>
            </span>
            <span>
              Claims: <strong className="text-white">{candidate.claims_count}</strong>
            </span>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                setOpenEvidenceId(isEvidenceOpen ? null : candidate.id);
                if (!isEvidenceOpen) setOpenReviewId(null);
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition cursor-pointer ${
                isEvidenceOpen
                  ? 'bg-indigo-600 text-white border-indigo-500'
                  : 'bg-white/[0.04] hover:bg-white/[0.08] text-zinc-200 border-white/[0.1]'
              }`}
            >
              <FileSearch className="w-3.5 h-3.5" />
              <span>{isEvidenceOpen ? 'Hide Evidence' : 'View Evidence'}</span>
            </button>

            {(isVerified || isProspect) && (
              <button
                type="button"
                onClick={() => {
                  setOpenReviewId(isReviewOpen ? null : candidate.id);
                  if (!isReviewOpen) setOpenEvidenceId(null);
                }}
                className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-bold border transition cursor-pointer ${
                  isReviewOpen
                    ? 'bg-emerald-600 text-white border-emerald-500'
                    : 'bg-emerald-500/15 hover:bg-emerald-500/25 text-emerald-300 border-emerald-500/30'
                }`}
              >
                <Send className="w-3.5 h-3.5" />
                <span>{isReviewOpen ? 'Close Review' : 'Review'}</span>
              </button>
            )}
          </div>
        </div>

        {/* EXPANDABLE DRAWER 1: IMMUTABLE EVIDENCE & CLAIMS LEDGER */}
        {isEvidenceOpen && (
          <div className="mt-3 pt-3 border-t border-white/[0.08] space-y-3 animate-in fade-in duration-200">
            <div className="flex items-center justify-between">
              <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-300 flex items-center gap-1.5">
                <Lock className="w-3 h-3" />
                Append-Only Evidence Records ({candidate.evidence.length})
              </span>
              {candidate.decision && (
                <span className="text-[10px] font-mono text-zinc-500">
                  decision_hash: {candidate.decision.decision_hash.slice(0, 12)}...
                </span>
              )}
            </div>

            {candidate.evidence.length === 0 ? (
              <div className="text-xs text-zinc-500 italic py-2">
                No structural evidence records extracted for this domain.
              </div>
            ) : (
              <div className="space-y-2">
                {candidate.evidence.map((ev, i) => (
                  <div
                    key={ev.id}
                    className="rounded-xl bg-black/60 border border-white/[0.07] p-3 text-xs space-y-1.5 font-mono"
                  >
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <div className="flex items-center gap-2">
                        <span className="px-1.5 py-0.5 rounded bg-indigo-500/20 text-indigo-300 font-bold text-[10px]">
                          E{i + 1}
                        </span>
                        <span className="text-white font-bold">{ev.supports_field}</span>
                        <span className="text-zinc-400">→</span>
                        <span className="text-emerald-300 font-bold">{ev.extracted_value}</span>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <span className="text-[10px] px-1.5 py-0.5 rounded bg-white/[0.05] text-zinc-300">
                          {ev.source_type}
                        </span>
                        <span
                          className={`text-[10px] px-1.5 py-0.5 rounded font-bold ${
                            ev.confidence === 'HIGH'
                              ? 'bg-emerald-500/20 text-emerald-300'
                              : ev.confidence === 'MEDIUM'
                              ? 'bg-amber-500/20 text-amber-300'
                              : 'bg-zinc-500/20 text-zinc-300'
                          }`}
                        >
                          {ev.confidence}
                        </span>
                      </div>
                    </div>
                    <div className="text-[11px] text-zinc-400">
                      Signal: <span className="text-zinc-200">{ev.signal_type}</span>
                    </div>
                    <div className="text-[11px] text-zinc-300 bg-white/[0.02] p-2 rounded border border-white/[0.04] overflow-x-auto">
                      {ev.raw_excerpt}
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Claims Breakdown */}
            {candidate.claims.length > 0 && (
              <div className="space-y-1.5 pt-2">
                <span className="text-[11px] font-bold uppercase tracking-wider text-zinc-400 block">
                  Validated Claims ({candidate.claims.length})
                </span>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {candidate.claims.map((cl) => (
                    <div
                      key={cl.id}
                      className="rounded-lg bg-black/40 border border-white/[0.06] px-3 py-2 text-xs font-mono flex items-center justify-between gap-2"
                    >
                      <div className="truncate">
                        <span className="text-zinc-400">{cl.field}: </span>
                        <span className="text-white font-semibold">{cl.value || '—'}</span>
                      </div>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded font-bold shrink-0 ${
                          cl.status === 'SUPPORTED'
                            ? 'bg-emerald-500/20 text-emerald-300'
                            : cl.status === 'CONTRADICTED'
                            ? 'bg-rose-500/20 text-rose-300'
                            : 'bg-amber-500/20 text-amber-300'
                        }`}
                      >
                        {cl.status}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}

        {/* EXPANDABLE DRAWER 2: CANDIDATE REVIEW & OUTREACH APPROVAL GATE */}
        {isReviewOpen && candidate.outreach_draft && (
          <div className="mt-3 pt-3 border-t border-white/[0.08] space-y-3 animate-in fade-in duration-200">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-bold text-emerald-300 flex items-center gap-1.5">
                <ShieldCheck className="w-4 h-4" />
                Whitelist-Validated Outreach Draft
              </span>
              <span className="text-[11px] text-zinc-400 font-mono">
                Zero unverified claims permitted
              </span>
            </div>

            {/* Allowed vs Blocked Claims */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 text-[11px] font-mono">
              <div className="rounded-xl bg-emerald-950/25 border border-emerald-500/25 p-2.5 space-y-1">
                <div className="text-emerald-400 font-bold uppercase text-[10px]">
                  ✓ Allowed in Outreach
                </div>
                {Object.entries(candidate.outreach_draft.allowed_claims || {}).map(([k, v]) => (
                  <div key={k} className="text-zinc-200 truncate">
                    • {k}: {Array.isArray(v) ? v.join(', ') : String(v)}
                  </div>
                ))}
              </div>

              <div className="rounded-xl bg-amber-950/20 border border-amber-500/25 p-2.5 space-y-1">
                <div className="text-amber-400 font-bold uppercase text-[10px]">
                  🔒 Blocked from Outreach (Unverified)
                </div>
                {Object.keys(candidate.outreach_draft.blocked_claims || {}).length === 0 ? (
                  <div className="text-zinc-400">None</div>
                ) : (
                  Object.entries(candidate.outreach_draft.blocked_claims || {}).map(([k, v]) => (
                    <div key={k} className="text-zinc-300 truncate" title={v}>
                      • {k}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Email Preview & Send Action */}
            <div className="rounded-xl bg-black/60 border border-white/[0.08] p-3.5 space-y-2.5 text-xs">
              <div className="flex flex-col sm:flex-row sm:items-center gap-2">
                <span className="text-zinc-400 font-mono w-16 shrink-0">To:</span>
                <input
                  type="email"
                  value={recipientOverrides[candidate.id] ?? candidate.outreach_draft.to}
                  onChange={(e) =>
                    setRecipientOverrides((prev) => ({
                      ...prev,
                      [candidate.id]: e.target.value
                    }))
                  }
                  className="flex-1 rounded-lg bg-[#0d121f] border border-white/[0.12] px-2.5 py-1 text-xs font-mono text-white focus:outline-none focus:border-indigo-500"
                />
              </div>
              <div className="flex items-center gap-2 border-b border-white/[0.06] pb-2">
                <span className="text-zinc-400 font-mono w-16 shrink-0">Subject:</span>
                <strong className="text-white">{candidate.outreach_draft.subject}</strong>
              </div>
              <div className="text-zinc-200 whitespace-pre-wrap leading-relaxed font-sans pt-1">
                {candidate.outreach_draft.body}
              </div>
            </div>

            <div className="flex items-center justify-end gap-2">
              <button
                type="button"
                disabled={queueingCandidateId === candidate.id}
                onClick={() => handleRequestOutreach(candidate)}
                className="flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-extrabold text-white bg-indigo-600 hover:bg-indigo-500 shadow-lg shadow-indigo-600/25 transition cursor-pointer disabled:opacity-50"
              >
                {queueingCandidateId === candidate.id ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>Routing to Policy Engine...</span>
                  </>
                ) : (
                  <>
                    <Send className="w-3.5 h-3.5" />
                    <span>Send Outreach to {candidate.company_name} (Requires Approval)</span>
                  </>
                )}
              </button>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-5 font-sans">
      {/* ==================== 1. APPROVAL REQUIRED BANNER (IF WAITING APPROVAL) ==================== */}
      {isWaitingApproval && ledger.pending_approval && (
        <div className="rounded-3xl border-2 border-amber-500/60 bg-gradient-to-b from-amber-950/35 via-[#10131e] to-[#090c14] p-5 sm:p-6 space-y-4 shadow-2xl">
          <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-amber-500/20 border border-amber-500/40 text-amber-300 text-xs font-black tracking-wider uppercase">
                <AlertTriangle className="w-4 h-4 text-amber-400" />
                <span>⚠ APPROVAL REQUIRED</span>
              </div>

              <div className="text-sm text-zinc-200 pt-1">
                Maya wants to send outreach to:{' '}
                <strong className="text-white font-black text-base block sm:inline">
                  {ledger.pending_approval.company_name}
                </strong>
                {ledger.pending_approval.canonical_domain && (
                  <span className="text-xs font-mono text-zinc-400 ml-1.5">
                    ({ledger.pending_approval.canonical_domain})
                  </span>
                )}
              </div>

              {/* Exact Governance Metadata Strip */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1 text-xs font-mono">
                <div className="rounded-xl bg-black/50 border border-white/[0.08] px-3 py-2">
                  <span className="text-zinc-500 block text-[10px] uppercase">Action</span>
                  <strong className="text-amber-300">{ledger.pending_approval.action}</strong>
                </div>
                <div className="rounded-xl bg-black/50 border border-white/[0.08] px-3 py-2">
                  <span className="text-zinc-500 block text-[10px] uppercase">Permission</span>
                  <strong className="text-indigo-300">{ledger.pending_approval.permission}</strong>
                </div>
                <div className="rounded-xl bg-black/50 border border-white/[0.08] px-3 py-2">
                  <span className="text-zinc-500 block text-[10px] uppercase">Reason</span>
                  <strong className="text-zinc-200">{ledger.pending_approval.reason}</strong>
                </div>
              </div>
            </div>

            {/* [Approve] [Reject] Buttons */}
            <div className="flex items-center gap-2.5 shrink-0">
              <button
                type="button"
                disabled={Boolean(approvingState)}
                onClick={() => handleApprovalDecision(true)}
                className="flex items-center gap-1.5 px-5 py-2.5 rounded-xl text-xs font-black text-white bg-emerald-600 hover:bg-emerald-500 shadow-lg shadow-emerald-600/30 transition cursor-pointer disabled:opacity-50"
              >
                {approvingState === 'approving' ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Check className="w-4 h-4" />
                )}
                <span>Approve</span>
              </button>

              <button
                type="button"
                disabled={Boolean(approvingState)}
                onClick={() => setRejectMode((prev) => !prev)}
                className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl text-xs font-bold text-zinc-200 hover:text-rose-200 bg-white/[0.06] hover:bg-rose-950/50 border border-white/[0.12] hover:border-rose-500/40 transition cursor-pointer disabled:opacity-50"
              >
                <X className="w-4 h-4" />
                <span>Reject</span>
              </button>
            </div>
          </div>

          {/* Outbound Email Payload Preview */}
          <div className="rounded-2xl bg-black/60 border border-amber-500/25 p-4 space-y-2 text-xs">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/[0.06] pb-2 font-mono">
              <div>
                <span className="text-zinc-500">To: </span>
                <strong className="text-white">{ledger.pending_approval.to}</strong>
              </div>
              <div>
                <span className="text-zinc-500">Subject: </span>
                <strong className="text-white">{ledger.pending_approval.subject}</strong>
              </div>
            </div>
            <div className="text-zinc-200 whitespace-pre-wrap leading-relaxed pt-1">
              {ledger.pending_approval.body}
            </div>
          </div>

          {/* Optional Rejection Feedback Box */}
          {rejectMode && (
            <div className="flex flex-col sm:flex-row gap-2 pt-1">
              <input
                type="text"
                value={rejectFeedback}
                onChange={(e) => setRejectFeedback(e.target.value)}
                placeholder="Optional feedback for Maya (e.g., 'Keep subject lines under 6 words for D2C founders')"
                className="flex-1 rounded-xl bg-black/60 border border-rose-500/40 px-3.5 py-2 text-xs text-white focus:outline-none"
              />
              <button
                type="button"
                disabled={Boolean(approvingState)}
                onClick={() => handleApprovalDecision(false)}
                className="px-4 py-2 rounded-xl text-xs font-black bg-rose-600 hover:bg-rose-500 text-white cursor-pointer shrink-0"
              >
                Confirm Reject
              </button>
            </div>
          )}
        </div>
      )}

      {/* ==================== 2. MAYA STATUS & TELEMETRY HEADER ==================== */}
      <div className="rounded-2xl border border-white/[0.1] bg-[#070a12] p-5 space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-white/[0.06]">
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <span className="text-sm font-black tracking-wider uppercase text-white">
                MAYA
              </span>
              {isWorking ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-bold text-sky-400">
                  <span className="w-2 h-2 rounded-full bg-sky-400 animate-pulse" />
                  Working
                </span>
              ) : isWaitingApproval ? (
                <span className="inline-flex items-center gap-1.5 text-xs font-bold text-amber-400">
                  <span className="w-2 h-2 rounded-full bg-amber-400 animate-ping" />
                  Awaiting Approval
                </span>
              ) : (
                <span className="inline-flex items-center gap-1.5 text-xs font-bold text-emerald-400">
                  <span className="w-2 h-2 rounded-full bg-emerald-400" />
                  Verified Complete
                </span>
              )}
            </div>
            <p className="text-xs text-zinc-300">
              <span className="text-zinc-500 font-semibold">Research: </span>
              {ledger.raw_prompt}
            </p>
          </div>

          <div className="px-3.5 py-2 rounded-xl bg-indigo-500/10 border border-indigo-500/30 text-right shrink-0">
            <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-300 block">
              Current stage
            </span>
            <span className="text-xs font-mono font-bold text-white">
              {ledger.current_stage_label}
            </span>
          </div>
        </div>

        {/* 4-Counter Telemetry Bar: Target | Verified | Prospects | Rejected */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono">
          <div className="rounded-xl bg-white/[0.02] border border-white/[0.06] px-3.5 py-2.5">
            <span className="text-[10px] text-zinc-500 uppercase block">Target</span>
            <span className="text-lg font-black text-white">{ledger.metrics.target}</span>
          </div>
          <div className="rounded-xl bg-emerald-500/[0.07] border border-emerald-500/25 px-3.5 py-2.5">
            <span className="text-[10px] text-emerald-400 uppercase block font-bold">Verified</span>
            <span className="text-lg font-black text-emerald-300">{ledger.metrics.verified}</span>
          </div>
          <div className="rounded-xl bg-amber-500/[0.07] border border-amber-500/25 px-3.5 py-2.5">
            <span className="text-[10px] text-amber-400 uppercase block font-bold">Prospects</span>
            <span className="text-lg font-black text-amber-300">{ledger.metrics.prospects}</span>
          </div>
          <div className="rounded-xl bg-rose-500/[0.06] border border-rose-500/20 px-3.5 py-2.5">
            <span className="text-[10px] text-rose-400 uppercase block font-bold">Rejected</span>
            <span className="text-lg font-black text-rose-300">{ledger.metrics.rejected}</span>
          </div>
        </div>
      </div>

      {/* ==================== 3. VERIFIED CANDIDATES SECTION ==================== */}
      {verifiedCandidates.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-emerald-500/25" />
            <span className="text-xs font-black uppercase tracking-widest text-emerald-400 font-mono">
              {verifiedCandidates.length} VERIFIED CANDIDATE{verifiedCandidates.length === 1 ? '' : 'S'}
            </span>
            <div className="h-px flex-1 bg-emerald-500/25" />
          </div>

          <div className="space-y-3">
            {verifiedCandidates.map((cand) => renderCandidateCard(cand))}
          </div>
        </div>
      )}

      {/* ==================== 4. PROSPECTS SECTION (UNVERIFIED PRIVATE METRICS) ==================== */}
      {prospectCandidates.length > 0 && (
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="h-px flex-1 bg-amber-500/25" />
            <span className="text-xs font-black uppercase tracking-widest text-amber-400 font-mono">
              {prospectCandidates.length} PROSPECT{prospectCandidates.length === 1 ? '' : 'S'} (UNVERIFIED PRIVATE METRICS)
            </span>
            <div className="h-px flex-1 bg-amber-500/25" />
          </div>

          <div className="space-y-3">
            {prospectCandidates.map((cand) => renderCandidateCard(cand))}
          </div>
        </div>
      )}

      {/* ==================== 5. REJECTED CANDIDATES SECTION (COLLAPSIBLE) ==================== */}
      {rejectedCandidates.length > 0 && (
        <div className="space-y-3 pt-1">
          <button
            type="button"
            onClick={() => setShowRejected(!showRejected)}
            className="w-full flex items-center justify-between px-4 py-2.5 rounded-xl bg-white/[0.02] hover:bg-white/[0.04] border border-white/[0.06] text-xs font-mono text-zinc-400 hover:text-zinc-200 transition cursor-pointer"
          >
            <span>
              {rejectedCandidates.length} REJECTED CANDIDATE{rejectedCandidates.length === 1 ? '' : 'S'} (Failed Verification / Contradicted)
            </span>
            {showRejected ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
          </button>

          {showRejected && (
            <div className="space-y-2.5">
              {rejectedCandidates.map((cand) => renderCandidateCard(cand))}
            </div>
          )}
        </div>
      )}

      {/* Empty State when 0 Viable Leads Survived */}
      {verifiedCandidates.length === 0 && prospectCandidates.length === 0 && !isWorking && (
        <div className="rounded-2xl border border-amber-500/25 bg-amber-950/15 p-5 text-center space-y-1.5">
          <div className="text-xs font-bold text-amber-300 uppercase tracking-wider">
            Epistemic Honesty Guardrail Active
          </div>
          <p className="text-xs text-zinc-300 max-w-xl mx-auto">
            0 candidates satisfied all hard verification requirements across {ledger.current_hop}/{ledger.max_hops} hops. Maya refused to manufacture unverified leads.
          </p>
        </div>
      )}
    </div>
  );
}
