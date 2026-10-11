"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRole } from "@/components/Providers";
import { api, type AskResult, type CatalogRow, type DqPayload, type QuestionResult, type Role, type XwalkRow } from "@/lib/api";

const cell = (v: unknown) => (v === null || v === undefined ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v));
const dimColor: Record<string, string> = { completeness: "bg-blue-50", validity: "bg-purple-50", consistency: "bg-amber-50", timeliness: "bg-teal-50" };

function Freshness({ days }: { days: number | null }) {
  if (days === null) return <span className="text-gray-400">—</span>;
  const w = Math.max(4, 100 - Math.min(days, 30) * 3);
  return <div className="flex items-center gap-2"><div className="h-2 w-24 rounded bg-gray-100"><div className={`h-2 rounded ${days > 7 ? "bg-red-400" : days > 3 ? "bg-amber-400" : "bg-green-500"}`} style={{ width: `${w}%` }} /></div><span className="text-xs text-gray-500">{days}d</span></div>;
}

function Catalog() {
  const { role } = useRole();
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const rows = useQuery({ queryKey: ["catalog", q, role], queryFn: () => api<CatalogRow[]>(`/hub/catalog${q ? `?q=${encodeURIComponent(q)}` : ""}`, role) });
  return (
    <section>
      <h2 className="mb-1 font-medium">Catalog</h2>
      <form className="mb-2 flex gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); setQ(text.trim()); }}>
        <input className="w-72 rounded border px-2 py-1" placeholder="search tables, e.g. lab results" value={text} onChange={(e) => setText(e.target.value)} />
        <button className="rounded border px-3 py-1 hover:bg-gray-100">Search</button>
      </form>
      {rows.error && <p className="text-red-700">{(rows.error as Error).message}</p>}
      <div className="max-h-72 overflow-y-auto">
        <table className="w-full text-sm"><thead className="sticky top-0 bg-white text-left text-gray-500"><tr><th>Table</th><th>Description</th><th>Owner</th><th>Rows</th><th>Freshness</th><th>Sensitivity</th></tr></thead>
          <tbody>{(rows.data ?? []).map((r) => (<tr key={r.table_name} className="border-t align-top"><td className="py-0.5 font-mono">{r.table_name}</td><td>{r.description}</td><td>{r.owner}</td><td className="font-mono">{r.row_count}</td><td><Freshness days={r.age_days} /></td><td>{r.sensitivity}</td></tr>))}</tbody></table>
      </div>
    </section>
  );
}

function Crosswalk() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [entity, setEntity] = useState<"subject" | "site">("subject");
  const [status, setStatus] = useState("");
  const [typed, setTyped] = useState<Record<string, string>>({});
  const rows = useQuery({ queryKey: ["xwalk", entity, status, role], queryFn: () => api<XwalkRow[]>(`/hub/xwalk?entity=${entity}${status ? `&status=${status}` : ""}`, role) });
  const act = useMutation({
    mutationFn: ({ r, action }: { r: XwalkRow; action: "confirm" | "reject" }) =>
      api(`/hub/xwalk/${r.system}/${r.source_id}/${action}`, role, { method: "POST", body: JSON.stringify({ canonical: typed[`${r.system}|${r.source_id}`] || null }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["xwalk"] }),
  });
  return (
    <section>
      <h2 className="mb-1 font-medium">Crosswalk review</h2>
      <p className="mb-2 text-sm text-gray-500">How identifiers from other systems map to our subjects and sites. Everything starts as proposed; unmatched items need a person.</p>
      <div className="mb-2 flex items-center gap-2 text-sm">
        <select className="rounded border px-2 py-1" value={entity} onChange={(e) => setEntity(e.target.value as "subject" | "site")}><option value="subject">subjects</option><option value="site">sites</option></select>
        <select className="rounded border px-2 py-1" value={status} onChange={(e) => setStatus(e.target.value)}>{["", "unmatched", "proposed", "confirmed", "rejected"].map((s) => (<option key={s} value={s}>{s || "all statuses"}</option>))}</select>
        {act.error && <span className="text-red-700">{(act.error as Error).message}</span>}
      </div>
      <div className="max-h-72 overflow-y-auto"><table className="w-full text-sm">
        <thead className="sticky top-0 bg-white text-left text-gray-500"><tr><th>System</th><th>Source identifier</th><th>Maps to</th><th>Confidence</th><th>Method</th><th>Status</th><th></th></tr></thead>
        <tbody>{(rows.data ?? []).map((r) => { const k = `${r.system}|${r.source_id}`; return (
          <tr key={k} className="border-t"><td>{r.system}</td><td className="font-mono">{r.source_id}</td>
            <td className="font-mono">{r.canonical ?? <input className="w-32 rounded border px-1" placeholder={entity === "site" ? "site id" : "subject id"} value={typed[k] ?? ""} onChange={(e) => setTyped({ ...typed, [k]: e.target.value })} />}</td>
            <td>{r.confidence.toFixed(2)}</td><td className="max-w-xs truncate text-gray-600" title={r.method}>{r.method}</td><td>{r.status}</td>
            <td className="whitespace-nowrap">{r.status !== "confirmed" && <button className="mr-1 rounded border px-2 hover:bg-gray-100" onClick={() => act.mutate({ r, action: "confirm" })}>Confirm</button>}
              {r.status !== "rejected" && <button className="rounded border px-2 hover:bg-gray-100" onClick={() => act.mutate({ r, action: "reject" })}>Reject</button>}</td></tr>); })}</tbody></table></div>
    </section>
  );
}

function Dq() {
  const { role } = useRole();
  const q = useQuery({ queryKey: ["dq", role], queryFn: () => api<DqPayload>("/hub/dq", role) });
  if (q.error) return <section><h2 className="font-medium">Data quality</h2><p className="text-red-700">{(q.error as Error).message}</p></section>;
  return (
    <section>
      <h2 className="mb-1 font-medium">Data quality</h2>
      <div className="grid gap-3 md:grid-cols-2">
        {(q.data?.dimensions ?? []).map((d) => (
          <div key={d} className={`rounded border p-2 ${dimColor[d]}`}><h3 className="mb-1 text-sm font-medium capitalize">{d}</h3>
            <ul className="space-y-0.5 text-sm">{q.data!.rules.filter((r) => r.dimension === d).map((r) => (
              <li key={r.rule} className="flex justify-between gap-2"><span title={r.sample_pks.join(", ")}>{r.description}</span><span className={`font-mono ${r.failed_rows ? "text-red-700" : "text-green-700"}`}>{r.failed_rows}</span></li>))}</ul></div>))}
      </div>
      <h3 className="mt-3 text-sm font-medium">Freshness</h3>
      <div className="grid gap-x-6 gap-y-1 md:grid-cols-2">{(q.data?.freshness ?? []).map((f) => (<div key={f.table} className="flex items-center justify-between text-sm"><span className="font-mono">{f.table}</span><Freshness days={f.age_days} /></div>))}</div>
    </section>
  );
}

async function ask(n: number, role: Role, scope?: string): Promise<QuestionResult | { error: string }> {
  try {
    const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api"}/hub/questions/${n}`, { headers: { "X-Role": role, "X-User": "demo_user", ...(scope ? { "X-Site-Scope": scope } : {}) } });
    if (!res.ok) return { error: ((await res.json()) as { detail: string }).detail };
    return (await res.json()) as QuestionResult;
  } catch (e) { return { error: (e as Error).message }; }
}

function ResultTable({ r }: { r: QuestionResult | { error: string } | undefined }) {
  if (!r) return <p className="text-sm text-gray-500">—</p>;
  if ("error" in r) return <p className="text-sm text-red-700">{r.error}</p>;
  return (
    <div className="text-xs">
      <p className="mb-1 text-gray-600">{r.level}{r.note ? ` — ${r.note}` : ""} · {r.rows.length} rows</p>
      <div className="max-h-48 overflow-auto"><table><thead className="text-left text-gray-500"><tr>{r.columns.map((c) => (<th key={c} className="pr-3">{c}</th>))}</tr></thead>
        <tbody>{r.rows.slice(0, 50).map((row, i) => (<tr key={i}>{r.columns.map((c) => (<td key={c} className="pr-3 font-mono">{cell(row[c])}</td>))}</tr>))}</tbody></table></div>
    </div>
  );
}

function Questions() {
  const { role } = useRole();
  const [n, setN] = useState(1);
  const list = useQuery({ queryKey: ["questions", role], queryFn: () => api<Array<{ id: number; title: string }>>("/hub/questions", role) });
  const mine = useQuery({ queryKey: ["question", n, role], queryFn: async () => { const r = await ask(n, role); if ("error" in r) throw new Error(r.error); return r; } });
  const [demo, setDemo] = useState<Array<[string, QuestionResult | { error: string }]>>([]);
  async function runDemo() {
    setDemo([["data_manager", await ask(n, "data_manager")], ["study_lead", await ask(n, "study_lead")], ["data_manager, site 701 only", await ask(n, "data_manager", "701")]]);
  }
  return (
    <section>
      <h2 className="mb-1 font-medium">Cross-system questions</h2>
      <div className="mb-2 flex flex-wrap items-center gap-2 text-sm">
        <select className="max-w-xl rounded border px-2 py-1" value={n} onChange={(e) => { setN(Number(e.target.value)); setDemo([]); }}>{(list.data ?? []).map((q) => (<option key={q.id} value={q.id}>{q.id}. {q.title}</option>))}</select>
        <button className="rounded border px-3 py-1 hover:bg-gray-100" onClick={runDemo}>Compare roles</button>
      </div>
      {mine.error ? <p className="text-sm text-red-700">{(mine.error as Error).message}</p> : mine.data && (
        <div className="space-y-1"><ResultTable r={mine.data} />
          <details className="text-xs"><summary className="cursor-pointer text-gray-600">Lineage: query and sources</summary>
            <pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2">{mine.data.lineage.sql}</pre><p>Tables: {mine.data.lineage.tables.join(", ")}</p></details></div>)}
      {demo.length > 0 && (<div className="mt-3 grid gap-3 md:grid-cols-3">{demo.map(([who, r]) => (<div key={who} className="rounded border p-2"><h3 className="mb-1 text-sm font-medium">{who}</h3><ResultTable r={r} /></div>))}</div>)}
    </section>
  );
}

function Ask() {
  const { role } = useRole();
  const [q, setQ] = useState("");
  const ask = useMutation({ mutationFn: () => api<AskResult>("/hub/ask", role, { method: "POST", body: JSON.stringify({ question: q }) }) });
  const r = ask.data;
  return (
    <section>
      <h2 className="mb-1 font-medium">Ask a question in plain English</h2>
      <p className="mb-2 text-sm text-gray-500">The question is turned into a read-only query over the hub views only. You see the query, the tables it used, and only the rows your role may see.</p>
      <form className="flex gap-2 text-sm" onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate(); }}>
        <input className="w-full max-w-xl rounded border px-2 py-1" placeholder="e.g. Which sites have the most open queries?" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="rounded border px-3 py-1 hover:bg-gray-100 disabled:opacity-50" disabled={ask.isPending}>{ask.isPending ? "Working…" : "Ask"}</button>
      </form>
      {ask.error && <p className="mt-1 text-sm text-red-700">{(ask.error as Error).message}</p>}
      {r && (<div className="mt-2 space-y-1"><p className="text-sm">{r.explanation} <span className="text-gray-500">({r.source})</span></p>
        <ResultTable r={{ id: 0, title: r.question, level: r.level, columns: r.columns, rows: r.rows, note: r.note, role, site_scope: null, lineage: { sql: r.sql, tables: r.lineage.tables, row_refs: [] } }} />
        <details className="text-xs"><summary className="cursor-pointer text-gray-600">Lineage: the query that ran</summary><pre className="mt-1 overflow-x-auto rounded bg-gray-50 p-2">{r.sql}</pre><p>Tables: {r.lineage.tables.join(", ")}</p></details></div>)}
    </section>
  );
}

export default function HubPage() {
  return (
    <main className="space-y-8 p-6">
      <div><h1 className="text-xl font-semibold">Data hub</h1><p className="text-sm text-gray-500">The clinical database, central lab, safety database, site management and supply systems in one place: what exists, how it connects, and whether it can be trusted.</p></div>
      <Catalog /><Crosswalk /><Dq /><Questions /><Ask />
    </main>
  );
}
