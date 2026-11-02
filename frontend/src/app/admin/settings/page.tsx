"use client";

import { Activity } from "lucide-react";
import { useEffect, useState } from "react";

import { ErrorNote, PageHeader } from "@/components/admin/AdminShell";
import { Button, Card, Spinner } from "@/components/ui";
import { API_URL, api } from "@/lib/api";

function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-faint">not set</span>;
  if (typeof value === "boolean") return <span className={value ? "text-ok" : "text-mute"}>{value ? "on" : "off"}</span>;
  return <span className="font-mono text-[12.5px]">{String(value)}</span>;
}

export default function SettingsPage() {
  const [config, setConfig] = useState<Record<string, unknown> | null>(null);
  const [health, setHealth] = useState<Record<string, unknown> | null>(null);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch((e) => setError(e.message));
  }, []);

  const check = async () => {
    setChecking(true);
    try {
      setHealth(await api.health(true));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  const sections = config ? Object.entries(config).filter(([, v]) => typeof v === "object" && v !== null) : [];
  const flat = config ? Object.entries(config).filter(([, v]) => typeof v !== "object" || v === null) : [];

  return (
    <div className="mx-auto max-w-[1100px]">
      <PageHeader
        title="Settings"
        description="The effective configuration of the API (from backend/.env). Secrets such as API keys are never sent to the browser. Change values in .env and restart the backend."
        actions={
          <Button onClick={check} disabled={checking}>
            {checking ? <Spinner /> : <Activity size={15} />} Check model connection
          </Button>
        }
      />
      {error && <ErrorNote message={error} />}
      {health && (
        <Card className={`mb-4 p-4 text-[13.5px] ${health.status === "ok" ? "border-[#b7e0cb]" : "border-[#f3c9c5]"}`}>
          <div className="font-semibold">{health.status === "ok" ? "Connected" : "Problem detected"}</div>
          <div className="text-mute">
            Chat model {String(health.chat_model)} · embeddings {String(health.embedding_model)} ·{" "}
            {health.embeddings_reachable ? "embedding model reachable" : `embedding model not reachable: ${String(health.embeddings_error ?? "")}`}
          </div>
        </Card>
      )}
      {config && (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Card className="p-5">
            <h2 className="mb-3 text-[15px] font-semibold">General</h2>
            <dl className="grid grid-cols-[1fr_auto] gap-y-2 text-[13.5px]">
              <dt className="text-mute">API address</dt>
              <dd>
                <Value value={API_URL} />
              </dd>
              {flat.map(([k, v]) => (
                <div key={k} className="contents">
                  <dt className="text-mute">{k.replaceAll("_", " ")}</dt>
                  <dd className="text-right">
                    <Value value={v} />
                  </dd>
                </div>
              ))}
            </dl>
          </Card>
          {sections.map(([name, values]) => (
            <Card key={name} className="p-5">
              <h2 className="mb-3 text-[15px] font-semibold capitalize">{name.replaceAll("_", " ")}</h2>
              <dl className="grid grid-cols-[1fr_auto] gap-y-2 text-[13.5px]">
                {Object.entries(values as Record<string, unknown>).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-mute">{k.replaceAll("_", " ")}</dt>
                    <dd className="text-right">
                      <Value value={v} />
                    </dd>
                  </div>
                ))}
              </dl>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
