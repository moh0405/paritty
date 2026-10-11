"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ClassBadge } from "@/components/ClassBadge";
import { EvidencePanel } from "@/components/EvidencePanel";
import { VerificationBadge } from "@/components/VerificationBadge";
import { useRole } from "@/components/Providers";
import { api, type CaseVersions, type CausalityResult, type InboxRow, type OneSided, type SaePair, type SaeSummary } from "@/lib/api";

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

const CAT_COLOR: Record<string, string> = { certain: "text-red-600", probable: "text-orange-600", possible: "text-amber-500", unlikely: "text-gray-600", unassessable: "text-gray-400" };

function Causality({ caseId, subject }: { caseId: string; subject: string }) {
  const { role } = useRole();
  const [evidence, setEvidence] = useState<string | null>(null);
  const existing = useQuery({ queryKey: ["causality", caseId, role], queryFn: () => api<Array<CausalityResult & { body?: Record<string, unknown> }>>(`/causality?case_id=${caseId}`, role) });
  const run = useMutation({ mutationFn: () => api<CausalityResult>(`/recon/sae/cases/${caseId}/causality`, role, { method: "POST" }), onSuccess: () => existing.refetch() });
  const latest = existing.data?.[0] as (CausalityResult & { body?: { alternative_causes?: string[]; why_escalated?: string[]; finding_id?: string; source?: string } }) | undefined;
  const why = latest?.body?.why_escalated ?? [];
  return (
    <section>
      <h2>Causality assessment <span className="font-normal normal-case tracking-normal text-gray-400">(draft for review)</span></h2>
      <p className="mt-2 text-sm text-gray-500">Case {caseId} | {subject}</p>
      {latest ? (
        <div className="mt-2 space-y-3">
          <div className="flex flex-wrap items-center gap-3">
            <span className={`text-3xl font-bold capitalize ${CAT_COLOR[latest.category] ?? ""}`}>{latest.category}</span>
            <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-800">Confidence {Number(latest.confidence).toFixed(2)}</span>
          </div>
          {latest.escalate && <span className="inline-block rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700">{why.length ? `Escalate: ${why[0]}` : "Escalate to a medical monitor"}</span>}
          {why.length > 1 && <p className="text-xs text-amber-900">{why.slice(1).join("; ")}</p>}
          {(latest.body?.alternative_causes ?? []).length > 0 && (<div><h2>Alternative causes to consider</h2><p className="mt-1 text-sm">{latest.body!.alternative_causes!.join("; ")}</p></div>)}
          <div className="flex flex-wrap items-center gap-2"><VerificationBadge status={latest.verification_status} />
            {latest.body?.finding_id && <button className="text-sm text-teal-700 hover:underline" onClick={() => setEvidence(latest.body!.finding_id!)}>Open the evidence and citations</button>}</div>
        </div>
      ) : <p className="mt-3 text-sm text-gray-500">No assessment yet for this case.</p>}
      <div className="mt-4 flex flex-wrap gap-2">
        <button className="rounded-md bg-teal-600 px-4 py-2 text-sm font-semibold text-white hover:bg-teal-500 disabled:opacity-50" disabled={run.isPending} onClick={() => run.mutate()}>{run.isPending ? "Assessing…" : latest ? "Assess again" : "Assess"}</button>
      </div>
      {run.error && <p className="mt-2 text-xs text-red-700">{(run.error as Error).message}</p>}
      <p className="mt-3 text-xs text-gray-500">Decision support only: the medical monitor makes the call.</p>
      {evidence && <EvidencePanel findingId={evidence} onClose={() => setEvidence(null)} />}
    </section>
  );
}

const DOT: Record<string, string> = { clean: "bg-gray-400", acceptable: "bg-green-500", actionable: "bg-orange-500", critical: "bg-red-600" };
const CHIP: Record<string, string> = { clean: "bg-gray-100 text-gray-600", acceptable: "bg-green-100 text-green-700", actionable: "bg-orange-100 text-orange-700", critical: "bg-red-100 text-red-700" };

function Field({ cls, label, edc, safety, why, p }: { cls: string; label: string; edc: string; safety: string; why: string; p: SaePair }) {
  return (
    <div className="grid grid-cols-[1fr_1fr] gap-4 rounded-xl border bg-white p-4">
      <div className="flex gap-3"><span className={`mt-1.5 h-3 w-3 shrink-0 rounded-full ${DOT[cls]}`} />
        <div><div className="font-semibold">{label}: {edc}</div><span className={`mt-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${CHIP[cls]}`}>{cls === "acceptable" ? "Acceptable" : cls === "clean" ? "Matches" : cls === "critical" ? "Critical" : "Actionable"}: {why}</span></div></div>
      <div className="flex items-start gap-2"><div className="flex-1 font-semibold">{label}: {safety}</div>
        <div className="flex shrink-0 flex-col gap-1 text-[10px] font-semibold text-teal-700"><span className="rounded-full bg-teal-50 px-2 py-0.5">EDC AE {p.ae_id}</span><span className="rounded-full bg-teal-50 px-2 py-0.5">case {p.case_id}</span></div></div>
    </div>
  );
}

function PairDetail({ p }: { p: SaePair }) {
  const [versions, setVersions] = useState(false);
  const termSame = p.edc.term === p.safety.term;
  return (
    <div className="space-y-2 bg-gray-50 p-4">
      <div className="grid grid-cols-2 gap-4 px-1 text-[11px] font-semibold uppercase tracking-wider text-gray-500"><span>EDC</span><span>Safety database (latest version v{p.version})</span></div>
      <Field p={p} cls={termSame ? "clean" : "acceptable"} label="Event" edc={show(p.edc.term)} safety={show(p.safety.term)} why={termSame ? "same coded term" : `different wording, same coded term (${p.term_match.method})`} />
      {p.discrepancies.map((d) => (<Field key={d.field} p={p} cls={d.cls} label={d.field} edc={show(d.edc_value)} safety={show(d.safety_value)} why={d.reason} />))}
      {p.discrepancies.length === 0 && <p className="px-1 text-sm text-gray-600">EDC and the safety database agree on every compared field.</p>}
      <p className="px-1 text-xs text-gray-500">Term match: {p.term_match.method} ({p.term_match.score}){p.term_match.reason && `, ${p.term_match.reason}`} · pair score {p.score}</p>
      <button className="px-1 text-xs text-teal-700 hover:underline" onClick={() => setVersions(!versions)}>{versions ? "Hide" : "Show"} case versions ({p.case_id})</button>
      {versions && <Versions caseId={p.case_id} />}
    </div>
  );
}

function Lane({ title, items, empty }: { title: string; items: OneSided[]; empty: string }) {
  const { role } = useRole();
  const qc = useQueryClient();
  const send = useMutation({ mutationFn: (aeId: number) => api(`/mock-safety/submit/${aeId}`, role, { method: "POST" }), onSuccess: () => qc.invalidateQueries() });
  return (
    <div className="flex-1 rounded-xl border border-red-200 bg-red-50/50 p-4">
      <h3 className="mb-2 font-semibold text-red-900">{title} <span className="font-normal text-red-700">({items.length})</span></h3>
      {items.length === 0 && <p className="text-sm text-gray-500">{empty}</p>}
      <ul className="space-y-1 text-sm">
        {items.map((o) => {
          const x = o.ae ?? o.case!;
          return (
            <li key={o.ae ? `ae${o.ae.id}` : o.case!.case_id} className="rounded border p-1.5">
              <div className="flex items-center gap-2"><ClassBadge cls={o.class} /><span className="font-mono">{x.usubjid}</span><span>{x.term}</span></div>
              <div className="text-xs text-gray-600">onset {show(x.onset)} · {o.reason}</div>
              {o.kind === "edc_only" && o.ae && (
                <button className="mt-1 rounded border px-2 py-0.5 text-xs hover:bg-gray-100 disabled:opacity-50" disabled={send.isPending} onClick={() => send.mutate(o.ae!.id)}>Send to safety database</button>)}
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function Inbox() {
  const { role } = useRole();
  const q = useQuery({ queryKey: ["inbox", role], queryFn: () => api<InboxRow[]>("/mock-safety/cases", role) });
  return (
    <section>
      <h2 className="mb-1 font-medium">Mock safety database inbox</h2>
      <p className="mb-1 text-sm text-gray-500">Cases and follow-ups sent to the safety database from EDC. Messages that fail validation are kept here with the reason.</p>
      <table className="w-full text-sm"><thead className="text-left text-gray-500"><tr><th>Received</th><th>Case</th><th>Version</th><th>Subject</th><th>Event</th><th>Status</th></tr></thead>
        <tbody>{(q.data ?? []).map((r) => (<tr key={r.id} className="border-t"><td className="font-mono text-xs">{r.received_at.slice(0, 10)}</td><td className="font-mono">{r.safetyreportid}</td><td>v{r.version}</td><td className="font-mono">{r.subject_ref}</td><td>{r.term}</td>
          <td><span className={r.status === "received" ? "text-green-700" : "text-red-700"}>{r.status}</span>{r.errors && r.errors.length > 0 && <span className="text-xs text-red-700"> — {r.errors.join("; ")}</span>}</td></tr>))}
          {q.data?.length === 0 && <tr><td colSpan={6} className="p-2 text-gray-500">No messages yet.</td></tr>}</tbody></table>
    </section>
  );
}

export default function SaeReconPage() {
  const { role } = useRole();
  const [cls, setCls] = useState("");
  const [sel, setSel] = useState<number | null>(null);
  const summary = useQuery({ queryKey: ["sae-summary", role], queryFn: () => api<SaeSummary>("/recon/sae/summary", role) });
  const pairs = useQuery({ queryKey: ["sae-pairs", role, cls], queryFn: () => api<SaePair[]>(`/recon/sae/pairs${cls ? `?cls=${cls}` : ""}`, role) });
  const unmatched = useQuery({ queryKey: ["sae-unmatched", role], queryFn: () => api<{ edc_only: OneSided[]; safety_only: OneSided[]; pending: OneSided[] }>("/recon/sae/unmatched", role) });
  const c = summary.data?.counts;
  const rank: Record<string, number> = { critical: 0, actionable: 1, acceptable: 2, clean: 3 };
  const list = [...(pairs.data ?? [])].sort((a, b) => rank[a.overall] - rank[b.overall]);
  const selected = list.find((p) => p.ae_id === sel) ?? list.find((p) => p.needs_causality) ?? list[0];
  const oneSided = (c?.edc_only ?? 0) + (c?.safety_only ?? 0);
  const cards: Array<[string, number | undefined, string]> = [["Matched pairs", c?.pairs, "text-gray-900"], ["Acceptable", c?.acceptable, "text-green-600"], ["Actionable", c?.actionable, "text-orange-500"], ["Critical", c?.critical, "text-red-600"], ["One-sided cases", oneSided, "text-amber-500"]];
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>SAE reconciliation</h1>
        <p className="mt-1 text-sm text-gray-500">EDC versus safety database. Acceptable differences are separated from ones that need action.</p>
      </div>
      {summary.error && <p className="text-red-700">{(summary.error as Error).message}</p>}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        {cards.map(([label, n, color]) => (
          <div key={label} className="card"><div className={`text-4xl font-bold ${color}`}>{n ?? "-"}</div><div className="mt-1 text-sm text-gray-500">{label}</div></div>))}
      </div>

      <div className="grid gap-5 xl:grid-cols-[1.8fr_1fr]">
        <div className="space-y-5">
          <section className="!p-0">
            <div className="flex items-center gap-3 px-5 pt-5"><h2>Side-by-side pairs</h2>
              <select className="ml-auto rounded-md border bg-white px-2 py-1 text-xs" value={cls} onChange={(e) => setCls(e.target.value)}>{["", "critical", "actionable", "acceptable", "clean"].map((x) => (<option key={x} value={x}>{x || "all results"}</option>))}</select></div>
            {pairs.error && <p className="px-5 text-red-700">{(pairs.error as Error).message}</p>}
            <ul className="mt-3 divide-y border-t">{list.map((p) => (
              <li key={p.ae_id}>
                <button className={`flex w-full items-center gap-3 px-5 py-3 text-left text-sm ${selected?.ae_id === p.ae_id ? "bg-teal-50/60" : "hover:bg-gray-50"}`} onClick={() => setSel(p.ae_id)}>
                  <span className={`h-3 w-3 shrink-0 rounded-full ${DOT[p.overall]}`} />
                  <span className="font-medium">{p.edc.term}</span><span className="text-gray-500">{p.usubjid}</span>
                  <span className="ml-auto flex flex-wrap items-center gap-1.5">
                    {p.needs_causality && <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-semibold text-purple-700">causality review</span>}
                    {p.open_items.map((o) => (<span key={o.check_id} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs">{o.check_id}{o.query_state ? ` · ${o.query_state}` : ""}</span>))}
                    <span className={`rounded-full px-2.5 py-0.5 text-xs font-semibold ${CHIP[p.overall]}`}>{p.overall}</span></span>
                </button>
                {selected?.ae_id === p.ae_id && <PairDetail p={p} />}
              </li>))}
              {list.length === 0 && <li className="px-5 py-4 text-sm text-gray-500">No pairs yet. Advance the clock.</li>}</ul>
          </section>

          {oneSided > 0 || (unmatched.data?.edc_only.length ?? 0) + (unmatched.data?.safety_only.length ?? 0) > 0 ? (
            <section className="!border-red-200 !bg-red-50/40">
              <h2 className="!text-red-800">Unmatched lanes</h2>
              <p className="mt-1 text-sm text-red-900">EDC only: {unmatched.data?.edc_only.length ?? 0} (serious AE with no safety case). Safety only: {unmatched.data?.safety_only.length ?? 0}. Both are listed as actionable.</p>
              <div className="mt-3 flex flex-wrap gap-3">
                <Lane title="In EDC, not in the safety database" items={unmatched.data?.edc_only ?? []} empty="None." />
                <Lane title="In the safety database, not in EDC" items={unmatched.data?.safety_only ?? []} empty="None." />
              </div>
            </section>) : null}

          <section>
            <h2>Progress to zero</h2>
            {summary.data && summary.data.history.length > 1 ? (
              <div className="mt-2 h-44">
                <ResponsiveContainer>
                  <LineChart data={summary.data.history}>
                    <CartesianGrid stroke="#eef0f3" vertical={false} /><XAxis dataKey="day" tick={{ fontSize: 11 }} minTickGap={40} /><YAxis allowDecimals={false} width={30} />
                    <Tooltip /><Line type="monotone" dataKey="open_discrepancies" name="open" stroke="#d97706" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="critical" stroke="#dc2626" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            ) : <p className="mt-2 text-sm text-gray-500">Advance the clock to build history.</p>}
          </section>
        </div>

        <div className="space-y-5">
          {selected ? <Causality key={selected.case_id} caseId={selected.case_id} subject={selected.usubjid ?? "unknown subject"} /> : <section><h2>Causality assessment</h2><p className="mt-2 text-sm text-gray-500">Pick a pair to see its causality assessment.</p></section>}
          <Inbox />
        </div>
      </div>
    </main>
  );
}
