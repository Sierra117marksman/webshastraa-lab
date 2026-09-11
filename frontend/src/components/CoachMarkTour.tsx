'use client';

import React, { useEffect, useState, useCallback } from 'react';
import {
  Sparkles,
  ChevronLeft,
  ChevronRight,
  X,
  Check,
  Zap,
  Users,
  KeyRound,
  BarChart3,
  Bot
} from 'lucide-react';

export interface TourStep {
  id: string;
  title: string;
  description: string;
  tab?: 'hire' | 'roster' | 'feed' | 'settings';
  targetId?: string;
  icon: React.ElementType;
  badge: string;
}

interface CoachMarkTourProps {
  isOpen: boolean;
  onClose: () => void;
  setActiveTab: (tab: 'hire' | 'roster' | 'feed' | 'settings') => void;
}

const TOUR_STEPS: TourStep[] = [
  {
    id: 'welcome',
    title: 'Welcome to Webshastraa AI',
    description:
      'The platform enabling non-tech founders to build, govern, and deploy autonomous AI employees in one prompt across marketing, CRM, HR, and ops.',
    badge: 'Overview',
    icon: Bot
  },
  {
    id: 'telemetry',
    title: 'Founder ROI & Value Telemetry',
    description:
      'Real-time tracking of hours saved (benchmarked against human virtual assistants), net dollar value created, and exact micro-API compute burn (~$0.0004 per task) ensuring 99.9% margin.',
    targetId: 'tour-telemetry',
    badge: 'Cost & Margin Guard',
    icon: Zap
  },
  {
    id: 'roster',
    title: 'Digital Workforce Roster',
    description:
      'View your specialized digital employees. Inspect their 5 Standard Operating Procedures (SOPs), safety gates, and dispatch custom missions on demand.',
    tab: 'roster',
    targetId: 'tour-roster',
    badge: 'Digital Team',
    icon: Users
  },
  {
    id: 'hire',
    title: 'Hire Studio & Prompt Compiler',
    description:
      'Enter your requirement in natural language or load a production blueprint. Gemini 3.6 Flash synthesizes identity, SOP checklists, live tool bindings, and safety gates.',
    tab: 'hire',
    targetId: 'tour-hire',
    badge: 'Meta-Agent',
    icon: Sparkles
  },
  {
    id: 'approvals',
    title: 'Execution & Approvals Station',
    description:
      'Zero rogue agent risk. External actions like Gmail SMTP dispatch pause here with full preview for your 1-click authorization before sending.',
    tab: 'feed',
    targetId: 'tour-approvals',
    badge: 'Safety Gate',
    icon: BarChart3
  },
  {
    id: 'governance',
    title: 'Integrations Hub & VIP Blacklist',
    description:
      'Manage Gemini, Tavily, and Gmail transports. Configure your VIP Blacklist guardrail to guarantee AI employees never email board members or key investors.',
    tab: 'settings',
    targetId: 'tour-settings',
    badge: 'Governance',
    icon: KeyRound
  }
];

export default function CoachMarkTour({ isOpen, onClose, setActiveTab }: CoachMarkTourProps) {
  const [currentStepIndex, setCurrentStepIndex] = useState(0);

  const step = TOUR_STEPS[currentStepIndex];
  const Icon = step?.icon || Sparkles;

  const handleNext = useCallback(() => {
    if (currentStepIndex < TOUR_STEPS.length - 1) {
      setCurrentStepIndex((prev) => prev + 1);
    } else {
      onClose();
    }
  }, [currentStepIndex, onClose]);

  const handlePrev = useCallback(() => {
    if (currentStepIndex > 0) {
      setCurrentStepIndex((prev) => prev - 1);
    }
  }, [currentStepIndex]);

  // Auto switch tab when step changes
  useEffect(() => {
    if (!isOpen) return;
    if (step && step.tab) {
      setActiveTab(step.tab);
    }
  }, [currentStepIndex, isOpen, step, setActiveTab]);

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowRight') {
        handleNext();
      } else if (e.key === 'ArrowLeft') {
        handlePrev();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, handleNext, handlePrev]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 select-none animate-in fade-in duration-200">
      {/* Darkened Backdrop */}
      <div
        onClick={onClose}
        className="absolute inset-0 bg-black/75 backdrop-blur-md transition-opacity cursor-pointer"
      />

      {/* Coach Mark Modal Spotlight Card */}
      <div className="relative w-full max-w-lg rounded-3xl border border-indigo-500/40 bg-gradient-to-b from-[#0e1322] to-[#07090f] p-6 sm:p-8 shadow-2xl shadow-indigo-950/60 ring-1 ring-white/10 z-10 space-y-6">
        {/* Top Header */}
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-2xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-violet-600 flex items-center justify-center text-white shadow-lg shadow-indigo-600/30">
              <Icon className="w-6 h-6" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-[10px] uppercase font-bold tracking-widest px-2 py-0.5 rounded-full bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                  {step.badge}
                </span>
                <span className="text-xs text-zinc-500 font-mono">
                  {currentStepIndex + 1} of {TOUR_STEPS.length}
                </span>
              </div>
              <h3 className="text-lg font-bold text-white tracking-tight mt-1">{step.title}</h3>
            </div>
          </div>

          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-xl text-zinc-400 hover:text-white hover:bg-white/[0.08] transition cursor-pointer"
            title="Close Tour (Esc)"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Description */}
        <p className="text-xs sm:text-sm text-zinc-300 leading-relaxed bg-black/30 p-4 rounded-2xl border border-white/[0.04]">
          {step.description}
        </p>

        {/* Progress Step Bar */}
        <div className="flex gap-1.5 items-center">
          {TOUR_STEPS.map((_, i) => (
            <button
              key={i}
              type="button"
              onClick={() => setCurrentStepIndex(i)}
              className={`h-1.5 rounded-full transition-all cursor-pointer ${
                i === currentStepIndex
                  ? 'w-8 bg-indigo-500 shadow-sm shadow-indigo-500/50'
                  : i < currentStepIndex
                  ? 'w-3 bg-indigo-500/40 hover:bg-indigo-400'
                  : 'w-3 bg-white/[0.1] hover:bg-white/[0.2]'
              }`}
              title={`Jump to step ${i + 1}`}
            />
          ))}
        </div>

        {/* Actions Footer */}
        <div className="flex items-center justify-between pt-2 border-t border-white/[0.06]">
          <button
            type="button"
            onClick={onClose}
            className="text-xs font-semibold text-zinc-500 hover:text-zinc-300 transition cursor-pointer"
          >
            Skip Tour
          </button>

          <div className="flex items-center gap-2">
            {currentStepIndex > 0 && (
              <button
                type="button"
                onClick={handlePrev}
                className="flex items-center gap-1 px-3.5 py-2 rounded-xl text-xs font-semibold text-zinc-400 hover:text-white bg-white/[0.04] hover:bg-white/[0.08] transition cursor-pointer"
              >
                <ChevronLeft className="w-3.5 h-3.5" />
                <span>Back</span>
              </button>
            )}

            <button
              type="button"
              onClick={handleNext}
              className="flex items-center gap-1.5 px-5 py-2 rounded-xl text-xs font-bold text-white bg-gradient-to-r from-indigo-600 to-violet-600 hover:from-indigo-500 hover:to-violet-500 shadow-lg shadow-indigo-600/30 transition active:scale-95 cursor-pointer"
            >
              {currentStepIndex === TOUR_STEPS.length - 1 ? (
                <>
                  <Check className="w-3.5 h-3.5" />
                  <span>Finish Tour</span>
                </>
              ) : (
                <>
                  <span>Next Step</span>
                  <ChevronRight className="w-3.5 h-3.5" />
                </>
              )}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
