export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10240 ? 1 : 0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function timeAgo(iso: string): string {
  const then = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`).getTime();
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.round(hours / 24);
  if (days < 7) return `${days} d ago`;
  return new Date(then).toLocaleDateString();
}

export function pct(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "–";
  return `${(value * 100).toFixed(digits)}%`;
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "–";
  return value.toFixed(digits);
}

export const FILE_TYPE_LABEL: Record<string, string> = {
  pdf: "PDF",
  docx: "Word",
  markdown: "Markdown",
  text: "Text",
  csv: "CSV",
  html: "HTML",
};

export const FILE_TYPE_STYLE: Record<string, string> = {
  pdf: "bg-bad-soft text-bad",
  docx: "bg-accent-soft text-accent-strong",
  csv: "bg-ok-soft text-ok",
  markdown: "bg-[#f0f1f4] text-ink-2",
  text: "bg-[#f0f1f4] text-ink-2",
  html: "bg-warn-soft text-warn",
};

export const ACCEPTED_FILES = ".pdf,.docx,.md,.markdown,.txt,.csv,.html,.htm";

export function locationLabel(page: number | null | undefined, section: string | null | undefined): string {
  const parts: string[] = [];
  if (page) parts.push(`Page ${page}`);
  if (section) parts.push(section);
  return parts.join(" · ");
}
