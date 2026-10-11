"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { EvidencePanel } from "@/components/EvidencePanel";
import { useRole } from "@/components/Providers";
import { VerificationBadge } from "@/components/VerificationBadge";
import { api, download, type Aging, type Digest, type QueryRow, type Stats } from "@/lib/api";

const STATES = ["", "Draft", "Approved", "Sent", "Answered", "Reopened", "Closed", "ClosedWithExplanation"];
const BADGE: Record<string, string> = {
  Draft: "bg-gray-100 text-gray-600", Approved: "bg-blue-100 text-blue-700", Sent: "bg-amber-100 text-amber-700",
  Answered: "bg-orange-100 text-orange-700", Reopened: "bg-red-100 text-red-700",
  Closed: "bg-green-100 text-green-700", ClosedWithExplanation: "bg-emerald-100 text-emerald-700",
};
const prioColor = (p: number, max: number) => { const r = p / Math.max(max, 0.0001); return r >= 0.75 ? "text-red-600" : r >= 0.5 ? "text-orange-500" : r >= 0.3 ? "text-amber-500" : "text-gray-400"; };

function Heatmap({ aging }: { aging: Aging }) {
  const max = Math.max(1, ...aging.rows.flatMap((r) => aging.buckets.map((b) => Number(r[b]))));
  const last = aging.buckets.length - 1;
  const cell = (i: number, n: number) => {
    if (!n) return { background: i >= last - 1 ? "#fef2f2" : "#eff6ff", color: "#374151" };
    const t = 0.25 + 0.75 * (n / max);
    return i >= last - 1 ? { background: `rgba(220,38,38,${t})`, color: t > 0.55 ? "#fff" : "#7f1d1d" } : { background: `rgba(59,130,246,${0.15 + 0.35 * t})`, color: "#1e3a8a" };
  };
  return (
    <table className="w-full border-separate border-spacing-1 text-sm">
      <thead><tr><th className="text-left"></th>{aging.buckets.map((b) => (<th key={b} className="text-center normal-case">{b}</th>))}</tr></thead>
      <tbody>
        {aging.rows.map((r) => (
          <tr key={String(r.site_id)}>
            <td className="pr-2 font-medium">Site {r.site_id}</td>
            {aging.buckets.map((b, i) => { const n = Number(r[b]); return (<td key={b} className="rounded-md py-2 text-center font-semibold" style={cell(i, n)}>{n}</td>); })}
          </tr>
        ))}
        {aging.rows.length === 0 && (<tr><td colSpan={5} className="text-gray-500">No open queries.</td></tr>)}
      </tbody>
    </table>
  );
}

export default function QueriesPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [state, setState] = useState("");
  const [site, setSite] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<string | null>(null);
  const params = new URLSearchParams({ limit: "300", ...(state && { state }), ...(site && { site }) });

  const list = useQuery({ queryKey: ["queries", role, state, site], queryFn: () => api<QueryRow[]>(`/queries?${params}`, role) });
  const aging = useQuery({ queryKey: ["aging", role], queryFn: () => api<Aging>("/queries/aging?by=site", role) });
  const digests = useQuery({ queryKey: ["digests", role], queryFn: () => api<Digest[]>("/digests", role) });
  const approveDigest = useMutation({ mutationFn: (id: string) => api(`/digests/${id}/approve`, role, { method: "POST" }), onSuccess: () => qc.invalidateQueries() });
  const stats = useQuery({ queryKey: ["qstats", role], queryFn: () => api<Stats>("/queries/stats", role) });

  const act = useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: "approve" | "close"; reason?: string }) =>
      api(`/queries/${id}/${action}`, role, { method: "POST", ...(action === "close" && { body: JSON.stringify({ reason: reason ?? "closed by data manager" }) }) }),
    onSuccess: () => qc.invalidateQueries(),
  });

  const [tr, setTr] = useState<Record<string, { language: string; text?: string; error?: string; busy?: boolean }>>({});
  async function translate(q: QueryRow) {
    const language = tr[q.id]?.language ?? "Spanish";
    setTr((t) => ({ ...t, [q.id]: { language, busy: true } }));
    try {
      const out = await api<{ text: string }>(`/queries/${q.id}/translate`, role, { method: "POST", body: JSON.stringify({ language }) });
      setTr((t) => ({ ...t, [q.id]: { language, text: out.text } }));
    } catch (e) { setTr((t) => ({ ...t, [q.id]: { language, error: (e as Error).message } })); }
  }
  const useTranslation = useMutation({
    mutationFn: ({ id, text, language }: { id: string; text: string; language: string }) => api(`/queries/${id}`, role, { method: "PATCH", body: JSON.stringify({ text, language }) }),
    onSuccess: () => qc.invalidateQueries(),
  });
  const isDM = role === "data_manager";
  const rows = list.data ?? [];
  const maxPrio = Math.max(0.0001, ...rows.map((q) => q.priority));
  const reopened = rows.filter((q) => q.reopen_count > 0 && q.state !== "Closed");
  const [find, setFind] = useState("");
  const shown = rows.filter((q) => !find || `${q.usubjid} ${q.site_id} ${q.check_description} ${q.text}`.toLowerCase().includes(find.toLowerCase()));
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>Queries</h1>
        <p className="mt-1 text-sm text-gray-500">Ranked by priority. Drafts need human approval before anything is sent to a site.</p>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        {Object.entries(stats.data?.by_state ?? {}).map(([s, n]) => (
          <button key={s} onClick={() => setState(state === s ? "" : s)} className={`rounded-full px-3 py-1 text-xs font-semibold ${BADGE[s] ?? "bg-gray-100"} ${state === s ? "ring-2 ring-offset-1 ring-blue-400" : ""}`}>{s} {n}</button>
        ))}
        <select className="rounded-md border bg-white px-2 py-1 text-xs" value={state} onChange={(e) => setState(e.target.value)}>{STATES.map((s) => (<option key={s} value={s}>{s || "all states"}</option>))}</select>
        <input className="w-20 rounded-md border bg-white px-2 py-1 text-xs" value={site} onChange={(e) => setSite(e.target.value)} placeholder="site" />
        <button className="rounded-md border bg-white px-2 py-1 text-xs hover:bg-gray-50" onClick={() => download("/export/queries.csv", role, "queries.csv").catch((e) => alert((e as Error).message))}>Export CSV</button>
        <input className="ml-auto w-72 rounded-md border bg-white px-3 py-2" placeholder="Search queries or subjects" value={find} onChange={(e) => setFind(e.target.value)} />
      </div>
      {(act.error || list.error) && <p className="text-sm text-red-600">{((act.error ?? list.error) as Error).message}</p>}

      <div className="grid gap-5 xl:grid-cols-[1.7fr_1fr]">
        <section className="!p-0">
          <h2 className="px-5 pt-5">Priority worklist</h2>
          <table className="mt-2 w-full text-sm">
            <thead><tr className="text-left"><th className="px-5 py-2">Pri</th><th>Site</th><th>Subject</th><th>Query</th><th className="pr-5">State</th></tr></thead>
            <tbody>
              {shown.map((q) => (
                <tr key={q.id} className={`group border-t align-top ${open === q.id ? "bg-blue-50/60" : "hover:bg-gray-50"}`}>
                  <td className={`px-5 py-3 text-lg font-bold ${prioColor(q.priority, maxPrio)}`}>{q.priority.toFixed(2)}</td>
                  <td className="py-3 pr-3">{q.site_id}</td>
                  <td className="py-3 pr-3 whitespace-nowrap text-gray-600">{q.usubjid}</td>
                  <td className="py-3 pr-3">
                    <button className="text-left font-medium hover:underline" onClick={() => setOpen(open === q.id ? null : q.id)}>{q.text.split("\n")[0].slice(0, 140) || q.check_description}</button>
                    <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-gray-500">
                      {q.finding_id ? (<button className="rounded-full bg-indigo-50 px-2 py-0.5 font-semibold text-indigo-700" onClick={() => setEvidence(q.finding_id)}>EDC row</button>) : null}
                      {q.finding_id && <VerificationBadge status={q.verification_status} />}
                      <span>severity {q.severity}</span><span>age {q.age_days}d</span>{q.text_source === "gemini" && <span>AI draft</span>}
                      {q.reopen_count > 0 && <span className="text-orange-700">reopened {q.reopen_count}x</span>}
                    </div>
                    {isDM && (
                      <div className="mt-2 flex gap-2">
                        {q.state === "Draft" && (<button className="rounded-md bg-blue-600 px-3 py-1 text-xs font-semibold text-white hover:bg-blue-500" onClick={() => act.mutate({ id: q.id, action: "approve" })}>Approve</button>)}
                        {["Draft", "Approved", "Sent", "Answered", "Reopened"].includes(q.state) && (<button className="rounded-md border bg-white px-3 py-1 text-xs font-semibold hover:bg-gray-50" onClick={() => act.mutate({ id: q.id, action: "close" })}>Close</button>)}
                      </div>)}
                    {open === q.id && (
                      <div className="mt-2 rounded-lg bg-white p-3 text-gray-700 ring-1 ring-gray-200">
                        <p className="whitespace-pre-wrap">{q.text}{q.closed_reason && <><br /><em>Closed: {q.closed_reason}</em></>}</p>
                        {isDM && q.state === "Draft" && (
                          <div className="mt-2 space-y-1 border-t pt-2 text-xs">
                            <div className="flex items-center gap-1">Translate for the site:
                              <select className="rounded border px-1" value={tr[q.id]?.language ?? "Spanish"} onChange={(e) => setTr((t) => ({ ...t, [q.id]: { language: e.target.value } }))}>{["Spanish", "French", "German", "Italian", "Portuguese", "Dutch", "Polish", "Japanese", "Chinese (Simplified)"].map((l) => (<option key={l}>{l}</option>))}</select>
                              <button className="rounded border px-2 hover:bg-gray-50" disabled={tr[q.id]?.busy} onClick={() => translate(q)}>{tr[q.id]?.busy ? "Translating…" : "Translate"}</button></div>
                            {tr[q.id]?.error && <p className="text-red-700">{tr[q.id].error}</p>}
                            {tr[q.id]?.text && (<><p className="rounded bg-gray-50 p-1">{tr[q.id].text}</p>
                              <button className="rounded border px-2 hover:bg-gray-50" onClick={() => useTranslation.mutate({ id: q.id, text: tr[q.id].text!, language: tr[q.id].language })}>Use this translation</button>
                              <span className="ml-2 text-gray-500">Every number, date and identifier was checked against the original.</span></>)}
                          </div>)}
                      </div>)}
                  </td>
                  <td className="py-3 pr-5"><span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${BADGE[q.state] ?? "bg-gray-100"}`}>{q.state}</span></td>
                </tr>
              ))}
              {shown.length === 0 && (<tr><td colSpan={5} className="p-5 text-gray-500">No queries yet. Advance the clock.</td></tr>)}
            </tbody>
          </table>
        </section>

        <div className="space-y-5">
          <section>
            <h2>Query aging by site <span className="font-normal normal-case tracking-normal text-gray-400">(days open)</span></h2>
            <div className="mt-2">{aging.data ? <Heatmap aging={aging.data} /> : <p className="text-gray-500">{aging.error ? (aging.error as Error).message : "Loading…"}</p>}</div>
          </section>
          <section>
            <h2>Reopened <span className="font-normal normal-case tracking-normal text-gray-400">(wrong correction, check still fails)</span></h2>
            {reopened.length === 0 && <p className="mt-2 text-sm text-gray-500">None right now.</p>}
            <ul className="mt-2 divide-y">{reopened.slice(0, 6).map((q) => (
              <li key={q.id} className="flex items-start gap-2 py-3"><div className="flex-1"><div className="font-semibold">{q.usubjid}</div><div className="text-sm text-gray-500">{q.check_description}</div></div>
                <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">{q.reopen_count === 1 ? "reopened" : `${q.reopen_count + 1}th time`}</span></li>))}</ul>
          </section>
        </div>
      </div>

      <section>
        <h2>Weekly digests of minor issues</h2>
        {(digests.data ?? []).length === 0 && <p className="mt-2 text-sm text-gray-500">No digests yet. Low-priority issues are grouped once a week per site.</p>}
        <ul className="mt-2 space-y-2">{(digests.data ?? []).slice(0, 8).map((d) => (
          <li key={d.id} className="rounded-lg border p-3 text-sm"><div className="flex items-center gap-2"><b>Site {d.site_id}</b><span className="text-gray-500">week of {d.week_of} · {d.queries} issues · {d.state}</span>
            {isDM && d.state === "Draft" && <button className="ml-auto rounded-md border px-2 py-0.5 hover:bg-gray-50" onClick={() => approveDigest.mutate(d.id)}>Approve digest</button>}</div>
            <pre className="mt-1 whitespace-pre-wrap text-xs text-gray-600">{d.text}</pre></li>))}</ul>
      </section>
      {evidence && <EvidencePanel findingId={evidence} onClose={() => setEvidence(null)} />}
    </main>
  );
}
