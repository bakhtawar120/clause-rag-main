"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Markdown answer where [1], [2] … become clickable citation chips. */
export function Answer({
  content,
  selected,
  onCite,
  validNumbers,
}: {
  content: string;
  selected: number | null;
  onCite: (n: number) => void;
  validNumbers: Set<number>;
}) {
  // [1] -> [1](#cite-1). Skip numbers that have no source (they are dropped server-side anyway).
  const linked = content.replace(/\[(\d+)\](?!\()/g, (match, n) => (validNumbers.has(Number(n)) ? `[${n}](#cite-${n})` : ""));
  return (
    <div className="prose-answer">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#cite-")) {
              const n = Number(href.slice(6));
              const active = selected === n;
              return (
                <button
                  type="button"
                  onClick={() => onCite(n)}
                  aria-label={`Show source ${n}`}
                  className={`mx-[1px] inline-flex h-[18px] min-w-[18px] -translate-y-[1px] items-center justify-center rounded-[5px] px-[5px] align-middle text-[11px] font-semibold transition-colors ${
                    active ? "bg-accent text-white" : "bg-accent-soft text-accent-strong hover:bg-[#d9e1fa]"
                  }`}
                >
                  {n}
                </button>
              );
            }
            return (
              <a href={href} target="_blank" rel="noreferrer" className="text-accent underline-offset-2 hover:underline">
                {children}
              </a>
            );
          },
          table: ({ children }) => (
            <div className="overflow-x-auto">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {linked}
      </ReactMarkdown>
    </div>
  );
}
