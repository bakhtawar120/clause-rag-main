"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { ErrorNote, PageHeader, Stat } from "@/components/admin/AdminShell";
import { Card, StatusPill } from "@/components/ui";
import { api } from "@/lib/api";
import { pct, timeAgo } from "@/lib/format";
import type { Stats } from "@/lib/types";

export default function OverviewPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.stats().then(setStats).catch((e) => setError(e.message));
  }, []);

  const lastEval = stats?.last_eval;
  const evalVariant = lastEval ? (lastEval.summary.hybrid_rerank ?? Object.values(lastEval.summary).at(-1)) : null;

  return (
    <div className="mx-auto max-w-[1200px]">
      <PageHeader title="Overview" description="Health of your documents, search index and answers at a glance." />
      {error && <ErrorNote message={error} />}
      {stats && (
        <div className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3.5 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Documents ready"
              value={`${stats.documents.ready}`}
              hint={`of ${stats.documents.total}${stats.documents.failed ? ` · ${stats.documents.failed} failed` : ""}`}
              tone={stats.documents.failed ? "bad" : undefined}
            />
            <Stat label="Indexed chunks" value={stats.index.vectors.toLocaleString()} hint={`${stats.chunks.toLocaleString()} in the database`} />
            <Stat label="Questions asked" value={stats.questions.toLocaleString()} hint={`${stats.conversations} conversations`} />
            <Stat
              label="“Not in your documents”"
              value={pct(stats.not_found_rate, 1)}
              hint={`${stats.feedback.up} helpful · ${stats.feedback.down} not helpful`}
              tone={stats.not_found_rate && stats.not_found_rate > 0.2 ? "warn" : undefined}
            />
          </div>

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-[15px] font-semibold">Latest evaluation</h2>
                <Link href="/admin/evaluation" className="text-[13px] text-accent hover:underline">
                  Open evaluation
                </Link>
              </div>
              {evalVariant ? (
                <div className="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3">
                  {[
                    ["Quality score", pct(evalVariant.quality_score)],
                    ["Right source in top 5", pct(evalVariant["hit@5"])],
                    ["Recall@5", pct(evalVariant["recall@5"])],
                    ["Key facts in answers", pct(evalVariant.key_facts)],
                    ["Correct refusals", pct(evalVariant.refusal_correct)],
                    ["Faithfulness", pct(evalVariant.faithfulness)],
                  ].map(([label, value]) => (
                    <div key={label}>
                      <div className="text-xs text-mute">{label}</div>
                      <div className="text-lg font-semibold tabular-nums">{value}</div>
                    </div>
                  ))}
                  <div className="col-span-full text-xs text-faint">Run {timeAgo(lastEval!.created_at)}</div>
                </div>
              ) : (
                <p className="text-[13.5px] text-mute">No evaluation yet. Run one to measure retrieval and answer quality.</p>
              )}
            </Card>

            <Card className="p-5">
              <h2 className="text-[15px] font-semibold">Content gaps</h2>
              <p className="mb-2 text-[12.5px] text-mute">Recent questions Clause could not answer from your documents</p>
              {stats.content_gaps.length === 0 ? (
                <p className="text-[13.5px] text-mute">Nothing yet. Every recent question found an answer.</p>
              ) : (
                <ul className="divide-y divide-line-soft">
                  {stats.content_gaps.map((g, i) => (
                    <li key={i} className="flex items-start justify-between gap-3 py-2.5">
                      <span className="text-[13.5px] font-medium">{g.question}</span>
                      <span className="shrink-0 text-xs text-faint">{timeAgo(g.asked_at)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card className="p-5">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">Recent documents</h2>
              <Link href="/admin/documents" className="text-[13px] text-accent hover:underline">
                Manage documents
              </Link>
            </div>
            {stats.recent_documents.length === 0 ? (
              <p className="text-[13.5px] text-mute">No documents yet.</p>
            ) : (
              <ul className="divide-y divide-line-soft">
                {stats.recent_documents.map((d) => (
                  <li key={d.id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
                    <span className="min-w-0 truncate text-[13.5px] font-medium">
                      {d.filename}
                      {d.in_chat && <span className="ml-2 text-xs font-normal text-faint">uploaded in a chat</span>}
                    </span>
                    <span className="flex items-center gap-3 text-xs text-mute">
                      {d.chunk_count} chunks <StatusPill status={d.status} /> {timeAgo(d.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
    </div>
  );
}
