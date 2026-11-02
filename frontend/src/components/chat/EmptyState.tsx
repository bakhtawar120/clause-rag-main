"use client";

import { Upload } from "lucide-react";

import { LogoMark } from "@/components/ui";

const SAMPLE_QUESTIONS = [
  { title: "Find a policy", q: "How many days of paid annual leave do employees get?" },
  { title: "Look up a price", q: "What is the price of SKU-4471?" },
  { title: "Compare two documents", q: "Compare the notice period in the employment contract with the notice period in the HR policy." },
  { title: "Get practical help", q: "My X200 headphones broke 10 days after delivery. Can I return them, or what happens?" },
];

export function EmptyState({
  libraryCount,
  onAsk,
  onPickFiles,
}: {
  libraryCount: number;
  onAsk: (q: string) => void;
  onPickFiles: () => void;
}) {
  return (
    <div className="mx-auto flex w-full max-w-[760px] flex-col items-center gap-6 pt-10 text-center sm:pt-16">
      <LogoMark size={44} />
      <div className="flex flex-col gap-1.5">
        <h1 className="text-balance text-[28px] font-semibold tracking-[-0.015em]">What do you want to find out?</h1>
        <p className="text-[15px] text-mute">
          {libraryCount > 0
            ? `Ask about your ${libraryCount} ${libraryCount === 1 ? "document" : "documents"}, or attach new files. Every answer shows where it came from.`
            : "Attach your documents to get started. Every answer shows where it came from."}
        </p>
      </div>

      <button
        type="button"
        onClick={onPickFiles}
        className="flex w-full flex-col items-center gap-2 rounded-2xl border-[1.5px] border-dashed border-[#c9ceda] bg-[#fafbfc] px-5 py-6 transition-colors hover:border-accent hover:bg-white"
      >
        <Upload size={24} className="text-mute" aria-hidden="true" />
        <span className="font-semibold">
          Drop files here, or <span className="text-accent">browse</span>
        </span>
        <span className="text-[12.5px] text-mute">PDF, Word, CSV, Markdown, plain text and HTML. You can add several at once.</span>
      </button>

      {libraryCount > 0 && (
        <div className="grid w-full grid-cols-1 gap-2.5 sm:grid-cols-2">
          {SAMPLE_QUESTIONS.map((s) => (
            <button
              key={s.q}
              type="button"
              onClick={() => onAsk(s.q)}
              className="rounded-xl border border-line bg-panel px-4 py-3.5 text-left transition-colors hover:border-[#c9ceda]"
            >
              <span className="block text-sm font-semibold">{s.title}</span>
              <span className="block text-[12.5px] text-mute">{s.q}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
