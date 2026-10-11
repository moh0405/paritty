"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { EvidencePanel } from "@/components/EvidencePanel";
import { useRole } from "@/components/Providers";
import { VerificationBadge } from "@/components/VerificationBadge";
import { api, type Aging, type QueryRow, type Stats } from "@/lib/api";

const STATES = ["", "Draft", "Approved", "Sent", "Answered", "Reopened", "Closed", "ClosedWithExplanation"];
const BADGE: Record<string, string> = {
  Draft: "bg-gray-200 text-gray-800", Approved: "bg-blue-100 text-blue-800", Sent: "bg-sky-100 text-sky-800",
  Answered: "bg-amber-100 text-amber-900", Reopened: "bg-orange-200 text-orange-900",
  Closed: "bg-green-100 text-green-800", ClosedWithExplanation: "bg-emerald-100 text-emerald-800",
};
const SEV: Record<string, string> = { critical: "text-red-600", major: "text-orange-600", minor: "text-gray-500" };

function Heatmap({ aging }: { aging: Aging }) {
  const max = Math.max(1, ...aging.rows.flatMap((r) => aging.buckets.map((b) => Number(r[b]))));
  return (
    <table className="text-sm">
      <thead>
        <tr><th className="pr-3 text-left font-medium">Site</th>{aging.buckets.map((b) => (<th key={b} className="px-2 font-medium">{b} d</th>))}</tr>
      </thead>
      <tbody>
        {aging.rows.map((r) => (
          <tr key={String(r.site_id)}>
            <td className="pr-3 font-mono">{r.site_id}</td>
            {aging.buckets.map((b) => {
              const n = Number(r[b]);
              return (
                <td key={b} className="px-2 py-0.5 text-center" style={{ background: n ? `rgba(234,88,12,${0.15 + 0.7 * (n / max)})` : undefined }}>
                  {n || ""}
                </td>
              );
            })}
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
  const stats = useQuery({ queryKey: ["qstats", role], queryFn: () => api<Stats>("/queries/stats", role) });

  const act = useMutation({
    mutationFn: ({ id, action, reason }: { id: string; action: "approve" | "close"; reason?: string }) =>
      api(`/queries/${id}/${action}`, role, { method: "POST", ...(action === "close" && { body: JSON.stringify({ reason: reason ?? "closed by data manager" }) }) }),
    onSuccess: () => qc.invalidateQueries(),
  });

  const isDM = role === "data_manager";
  return (
    <main className="space-y-6 p-6">
      <section>
        <h1 className="text-xl font-semibold">Query worklist</h1>
        <p className="text-sm text-gray-500">Ranked by priority = CTQ × severity × age × site. Drafts need a data manager&apos;s approval before they are sent.</p>
        <div className="mt-2 flex flex-wrap gap-2 text-sm">
          {Object.entries(stats.data?.by_state ?? {}).map(([s, n]) => (
            <span key={s} className={`rounded px-2 py-0.5 ${BADGE[s] ?? "bg-gray-100"}`}>{s}: {n}</span>
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-2 font-medium">Open queries by age and site</h2>
        {aging.data ? <Heatmap aging={aging.data} /> : <p className="text-gray-500">{aging.error ? (aging.error as Error).message : "Loading…"}</p>}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-3 text-sm">
          <label>State <select className="rounded border px-2 py-1" value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map((s) => (<option key={s} value={s}>{s || "all"}</option>))}</select></label>
          <label>Site <input className="w-20 rounded border px-2 py-1" value={site} onChange={(e) => setSite(e.target.value)} placeholder="all" /></label>
          {act.error && <span className="text-red-600">{(act.error as Error).message}</span>}
        </div>
        {list.error && <p className="text-red-600">{(list.error as Error).message}</p>}
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500">
              <tr><th className="p-1">Priority</th><th>State</th><th>Site</th><th>Subject</th><th>Issue</th><th>Evidence</th><th>Age</th><th></th></tr>
            </thead>
            <tbody>
              {(list.data ?? []).map((q) => (
                <tr key={q.id} className={`border-t align-top ${q.reopen_count > 0 && q.state !== "Closed" ? "bg-orange-50" : ""}`}>
                  <td className="p-1 font-mono">{q.priority.toFixed(2)}</td>
                  <td>
                    <span className={`rounded px-1.5 py-0.5 ${BADGE[q.state] ?? ""}`}>{q.state}</span>
                    {q.reopen_count > 0 && <span className="ml-1 text-orange-700" title="times reopened">↻{q.reopen_count}</span>}
                  </td>
                  <td className="font-mono">{q.site_id}</td>
                  <td className="font-mono">{q.usubjid}</td>
                  <td className="max-w-xl">
                    <button className="text-left hover:underline" onClick={() => setOpen(open === q.id ? null : q.id)}>
                      <span className={SEV[q.severity]}>●</span> {q.check_description}
                    </button>
                    {open === q.id && (<p className="mt-1 rounded bg-gray-50 p-2 text-gray-700">{q.text}{q.closed_reason && <><br /><em>Closed: {q.closed_reason}</em></>}</p>)}
                  </td>
                  <td className="whitespace-nowrap">
                    {q.finding_id && (
                      <button className="mr-1 hover:underline" onClick={() => setEvidence(q.finding_id)} title="Open evidence">
                        <VerificationBadge status={q.verification_status} />
                      </button>
                    )}
                    {q.text_source === "gemini" && <span className="text-xs text-gray-500">AI draft</span>}
                  </td>
                  <td>{q.age_days}d</td>
                  <td className="whitespace-nowrap">
                    {isDM && q.state === "Draft" && (<button className="mr-1 rounded border px-2 py-0.5 hover:bg-gray-100" onClick={() => act.mutate({ id: q.id, action: "approve" })}>Approve</button>)}
                    {isDM && ["Draft", "Approved", "Sent", "Answered", "Reopened"].includes(q.state) && (
                      <button className="rounded border px-2 py-0.5 hover:bg-gray-100" onClick={() => act.mutate({ id: q.id, action: "close" })}>Close</button>)}
                  </td>
                </tr>
              ))}
              {list.data?.length === 0 && (<tr><td colSpan={8} className="p-3 text-gray-500">No queries yet — advance the clock.</td></tr>)}
            </tbody>
          </table>
        </div>
      </section>
      {evidence && <EvidencePanel findingId={evidence} onClose={() => setEvidence(null)} />}
    </main>
  );
}
