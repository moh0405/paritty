"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ClassBadge } from "@/components/ClassBadge";
import { useRole } from "@/components/Providers";
import { api, type CaseVersions, type OneSided, type SaePair, type SaeSummary } from "@/lib/api";

const show = (v: unknown) => (v === null || v === undefined || v === "" ? "—" : String(v));

function Versions({ caseId }: { caseId: string }) {
  const { role } = useRole();
  const q = useQuery({ queryKey: ["versions", caseId, role], queryFn: () => api<CaseVersions>(`/recon/sae/cases/${caseId}/versions`, role) });
  if (q.isLoading) return <p className="text-xs text-gray-500">Loading versions…</p>;
  if (q.error) return <p className="text-xs text-red-700">{(q.error as Error).message}</p>;
  return (
    <ol className="mt-1 space-y-1 text-xs">
      {q.data!.versions.map((v) => (
        <li key={v.version} className="rounded border bg-white p-1.5">
          <span className="font-medium">v{v.version}</span> · received {show(v.received)} · available {show(v.available_on)}
          {v.changes && Object.keys(v.changes).length > 0 ? (
            <ul className="ml-3 list-disc">
              {Object.entries(v.changes).map(([k, c]) => (<li key={k}>{k}: {show(c.from)} → {show(c.to)}</li>))}
            </ul>
          ) : v.version > 1 ? <span className="text-gray-500"> — added detail only</span> : null}
        </li>
      ))}
    </ol>
  );
}

function PairRow({ p }: { p: SaePair }) {
  const [open, setOpen] = useState(false);
  const [versions, setVersions] = useState(false);
  return (
    <>
      <tr className="cursor-pointer border-t align-top hover:bg-gray-50" onClick={() => setOpen(!open)}>
        <td className="p-1"><ClassBadge cls={p.overall} /></td>
        <td className="font-mono">{p.usubjid}</td>
        <td>{p.edc.term}{p.safety.term !== p.edc.term && <span className="text-gray-500"> / {p.safety.term}</span>}</td>
        <td className="font-mono">{show(p.edc.onset)}</td>
        <td>v{p.version}</td>
        <td className="space-x-1">
          {p.needs_causality && <span className="rounded bg-purple-100 px-1 text-xs text-purple-800">needs causality review</span>}
          {p.open_items.map((o) => (<span key={o.check_id} className="rounded bg-gray-100 px-1 text-xs">{o.check_id}{o.query_state ? ` · ${o.query_state}` : ""}</span>))}
        </td>
      </tr>
      {open && (
        <tr className="bg-gray-50">
          <td colSpan={6} className="p-2">
            {p.discrepancies.length === 0 ? <p className="text-sm text-gray-600">EDC and the safety database agree on every compared field.</p> : (
              <table className="text-sm">
                <thead className="text-left text-gray-500"><tr><th className="pr-4">Field</th><th className="pr-4">EDC</th><th className="pr-4">Safety database</th><th className="pr-4">Class</th><th>Why</th></tr></thead>
                <tbody>
                  {p.discrepancies.map((d) => (
                    <tr key={d.field}><td className="pr-4">{d.field}</td><td className="pr-4 font-mono">{show(d.edc_value)}</td>
                      <td className="pr-4 font-mono">{show(d.safety_value)}</td><td className="pr-4"><ClassBadge cls={d.cls} /></td><td className="text-gray-600">{d.reason}</td></tr>
                  ))}
                </tbody>
              </table>
            )}
            <p className="mt-1 text-xs text-gray-500">Term match: {p.term_match.method} ({p.term_match.score}){p.term_match.reason && ` — ${p.term_match.reason}`} · pair score {p.score}</p>
            <button className="mt-1 text-xs text-blue-700 hover:underline" onClick={(e) => { e.stopPropagation(); setVersions(!versions); }}>
              {versions ? "Hide" : "Show"} case versions ({p.case_id})
            </button>
            {versions && <Versions caseId={p.case_id} />}
          </td>
        </tr>
      )}
    </>
  );
}

function Lane({ title, items, empty }: { title: string; items: OneSided[]; empty: string }) {
  return (
    <div className="flex-1 rounded border p-3">
      <h3 className="mb-2 font-medium">{title} <span className="text-gray-500">({items.length})</span></h3>
      {items.length === 0 && <p className="text-sm text-gray-500">{empty}</p>}
      <ul className="space-y-1 text-sm">
        {items.map((o) => {
          const x = o.ae ?? o.case!;
          return (
            <li key={o.ae ? `ae${o.ae.id}` : o.case!.case_id} className="rounded border p-1.5">
              <div className="flex items-center gap-2"><ClassBadge cls={o.class} /><span className="font-mono">{x.usubjid}</span><span>{x.term}</span></div>
              <div className="text-xs text-gray-600">onset {show(x.onset)} · {o.reason}</div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

export default function SaeReconPage() {
  const { role } = useRole();
  const [cls, setCls] = useState("");
  const summary = useQuery({ queryKey: ["sae-summary", role], queryFn: () => api<SaeSummary>("/recon/sae/summary", role) });
  const pairs = useQuery({ queryKey: ["sae-pairs", role, cls], queryFn: () => api<SaePair[]>(`/recon/sae/pairs${cls ? `?cls=${cls}` : ""}`, role) });
  const unmatched = useQuery({ queryKey: ["sae-unmatched", role], queryFn: () => api<{ edc_only: OneSided[]; safety_only: OneSided[]; pending: OneSided[] }>("/recon/sae/unmatched", role) });
  const c = summary.data?.counts;
  const chips: Array<[string, number | undefined]> = [["clean", c?.clean], ["acceptable", c?.acceptable], ["actionable", c?.actionable], ["critical", c?.critical]];
  return (
    <main className="space-y-6 p-6">
      <section>
        <h1 className="text-xl font-semibold">Serious adverse event reconciliation</h1>
        <p className="text-sm text-gray-500">EDC serious adverse events matched to the safety database. Acceptable differences are shown but do not raise queries.</p>
        {summary.error && <p className="mt-2 text-red-700">{(summary.error as Error).message}</p>}
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          {chips.map(([k, n]) => (<span key={k} className="flex items-center gap-1"><ClassBadge cls={k} /> {n ?? "—"}</span>))}
          <span>EDC only: <b>{c?.edc_only ?? "—"}</b></span><span>Safety only: <b>{c?.safety_only ?? "—"}</b></span>
          {!!c?.pending && <span className="text-gray-500">{c.pending} within reporting window</span>}
          <span className="ml-auto text-gray-600">Open discrepancies: <b>{c?.open_discrepancies ?? "—"}</b></span>
        </div>
      </section>

      <section>
        <h2 className="mb-1 font-medium">Progress to zero</h2>
        {summary.data && summary.data.history.length > 1 ? (
          <div className="h-44 max-w-3xl">
            <ResponsiveContainer>
              <LineChart data={summary.data.history}>
                <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tick={{ fontSize: 11 }} minTickGap={40} /><YAxis allowDecimals={false} width={30} />
                <Tooltip /><Line type="monotone" dataKey="open_discrepancies" name="open" stroke="#d97706" dot={false} strokeWidth={2} />
                <Line type="monotone" dataKey="critical" stroke="#dc2626" dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : <p className="text-sm text-gray-500">Advance the clock to build history.</p>}
      </section>

      <section>
        <div className="mb-2 flex items-center gap-2 text-sm">
          <h2 className="font-medium">Matched pairs</h2>
          <select className="rounded border px-2 py-1" value={cls} onChange={(e) => setCls(e.target.value)}>
            {["", "critical", "actionable", "acceptable", "clean"].map((s) => (<option key={s} value={s}>{s || "all"}</option>))}
          </select>
        </div>
        {pairs.error && <p className="text-red-700">{(pairs.error as Error).message}</p>}
        <table className="w-full text-sm">
          <thead className="text-left text-gray-500"><tr><th className="p-1">Result</th><th>Subject</th><th>Event (EDC / safety)</th><th>EDC onset</th><th>Case</th><th>Open items</th></tr></thead>
          <tbody>{(pairs.data ?? []).map((p) => <PairRow key={p.ae_id} p={p} />)}</tbody>
        </table>
      </section>

      <section className="flex flex-wrap gap-3">
        <Lane title="In EDC, not in the safety database" items={unmatched.data?.edc_only ?? []} empty="None." />
        <Lane title="In the safety database, not in EDC" items={unmatched.data?.safety_only ?? []} empty="None." />
      </section>
    </main>
  );
}
