"use client";

import * as React from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { CitationChip } from "@/components/chat/citation-chip";
import { injectCitationLinks, parseCitationHref } from "@/lib/citations";
import { cn } from "@/lib/utils";

export function AnswerMarkdown({
  content,
  availableIndices,
  activeIndex,
  onCitationSelect,
  className,
}: {
  content: string;
  availableIndices: number[];
  activeIndex?: number | null;
  onCitationSelect?: (index: number) => void;
  className?: string;
}) {
  const prepared = React.useMemo(() => injectCitationLinks(content), [content]);
  const available = React.useMemo(() => new Set(availableIndices), [availableIndices]);

  return (
    <div className={cn("prose-aqua", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children, ...props }) => {
            const citationIndex = parseCitationHref(href);
            if (citationIndex !== null) {
              return (
                <CitationChip
                  index={citationIndex}
                  hasSource={available.has(citationIndex)}
                  active={activeIndex === citationIndex}
                  onSelect={onCitationSelect}
                />
              );
            }
            return (
              <a
                href={href}
                target="_blank"
                rel="noreferrer noopener"
                {...props}
              >
                {children}
              </a>
            );
          },
          table: ({ children, ...props }) => (
            <div className="my-3 overflow-x-auto rounded-lg border border-border">
              <table {...props}>{children}</table>
            </div>
          ),
        }}
      >
        {prepared}
      </ReactMarkdown>
    </div>
  );
}
