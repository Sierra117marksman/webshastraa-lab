'use client';

import React from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { ExternalLink } from 'lucide-react';

interface MarkdownViewerProps {
  content: string;
  className?: string;
}

export default function MarkdownViewer({ content, className = '' }: MarkdownViewerProps) {
  if (!content) return null;

  return (
    <div className={`markdown-body text-zinc-200 font-sans leading-relaxed selection:bg-indigo-500/40 ${className}`}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => (
            <div className="overflow-x-auto my-4 rounded-2xl border border-white/10 bg-white/[0.02] shadow-sm">
              <table className="w-full text-left border-collapse text-xs min-w-[600px]">
                {children}
              </table>
            </div>
          ),
          thead: ({ children }) => (
            <thead className="bg-white/[0.06] text-zinc-200 font-mono text-[11px] tracking-wider border-b border-white/10">
              {children}
            </thead>
          ),
          th: ({ children }) => (
            <th className="px-4 py-3 font-bold text-zinc-200">
              {children}
            </th>
          ),
          tbody: ({ children }) => (
            <tbody className="divide-y divide-white/[0.05]">
              {children}
            </tbody>
          ),
          tr: ({ children }) => (
            <tr className="hover:bg-white/[0.04] transition-colors">
              {children}
            </tr>
          ),
          td: ({ children }) => (
            <td className="px-4 py-3 text-zinc-300 align-top leading-relaxed">
              {children}
            </td>
          ),
          h1: ({ children }) => (
            <h1 className="text-base sm:text-lg font-black text-white mt-6 mb-3 pb-2 border-b border-white/10 tracking-tight flex items-center gap-2.5">
              <span className="w-1.5 h-4.5 rounded-full bg-indigo-500 shrink-0"></span>
              <span>{children}</span>
            </h1>
          ),
          h2: ({ children }) => (
            <h2 className="text-sm sm:text-base font-extrabold text-white mt-5 mb-2.5 tracking-tight flex items-center gap-2">
              <span className="w-1.5 h-3.5 rounded-full bg-sky-500 shrink-0"></span>
              <span>{children}</span>
            </h2>
          ),
          h3: ({ children }) => (
            <h3 className="text-xs sm:text-sm font-bold text-zinc-100 mt-4 mb-2 tracking-tight">
              {children}
            </h3>
          ),
          p: ({ children }) => (
            <p className="text-xs text-zinc-300 leading-relaxed my-2.5">
              {children}
            </p>
          ),
          a: ({ href, children }) => (
            <a
              href={href}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-semibold text-sky-400 hover:text-sky-300 underline underline-offset-2 transition-colors cursor-pointer"
            >
              <span>{children}</span>
              <ExternalLink className="w-3 h-3 inline-block shrink-0 opacity-80" />
            </a>
          ),
          ul: ({ children }) => (
            <ul className="list-disc list-outside space-y-1.5 my-3 text-xs text-zinc-300 pl-5">
              {children}
            </ul>
          ),
          ol: ({ children }) => (
            <ol className="list-decimal list-outside space-y-1.5 my-3 text-xs text-zinc-300 pl-5">
              {children}
            </ol>
          ),
          li: ({ children }) => (
            <li className="text-xs text-zinc-300 leading-relaxed">
              {children}
            </li>
          ),
          strong: ({ children }) => (
            <strong className="font-bold text-white">
              {children}
            </strong>
          ),
          blockquote: ({ children }) => (
            <blockquote className="border-l-2 border-indigo-500 bg-indigo-500/[0.06] rounded-r-xl px-4 py-2.5 my-3 text-xs text-zinc-200">
              {children}
            </blockquote>
          ),
          code: ({ className, children, ...props }: any) => {
            const isInline = !className && typeof children === 'string' && !children.includes('\n');
            if (isInline) {
              return (
                <code className="font-mono text-[11px] px-1.5 py-0.5 rounded bg-white/[0.08] text-amber-300 border border-white/[0.06]">
                  {children}
                </code>
              );
            }
            return (
              <pre className="font-mono text-[11px] p-3.5 rounded-xl bg-black/70 border border-white/10 text-zinc-200 overflow-x-auto my-3">
                <code>{children}</code>
              </pre>
            );
          },
          hr: () => <hr className="my-5 border-white/[0.08]" />
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
