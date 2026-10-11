"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams } from "next/navigation";
import { Suspense } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RagDot } from "@/components/Rag";
import { useRole } from "@/components/Providers";
import { api, API_BASE, type Issue, type SiteDetail } from "@/lib/api";

export default function SitePage() {
  // useParams() is request-time data: without a boundary it blocks prerendering of the whole route (Next.js cache components)
  return <Suspense fallback={<main className="p-6 text-gray-500">Loading…</main>}><SiteView /></Suspense>;
}

function SiteView() {
  const { id } = useParams<{ id: string }>();
  const { role } = useRole();
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["site", id, role], queryFn: () => api<SiteDetail>(`/sites/${id}`, role) });
  const setStatus = useMutation({ mutationFn: ({ issue, status }: { issue: string; status: Issue["status"] }) =>
    api<Issue>(`/issues/${issue}`, role, { method: "PATCH", body: JSON.stringify({ status }) }), onSuccess: () => qc.invalidateQueries({ queryKey: ["site", id] }) });
  const canAct = role === "central_monitor" || role === "data_manager";
  async function openScorecard() {      // fetched with the role header, so it cannot be a plain link
    const res = await fetch(`${API_BASE}/sites/${id}/scorecard.pdf`, { headers: { "X-Role": role, "X-User": "demo_user" } });
    if (res.ok) window.open(URL.createObjectURL(await res.blob()), "_blank");
  }
  if (q.error) return <main className="p-6 text-red-700">{(q.error as Error).message}</main>;
  if (!q.data) return <main className="p-6 text-gray-500">Loading…</main>;
  const s = q.data;
  const digits = s.anomalies.find((a) => a.test === "terminal_digit")?.detail.digit_counts as number[] | undefined;
  const variance = s.anomalies.find((a) => a.test === "variance_ratio")?.detail.ratio as number | undefined;
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>Site <span className="font-mono">{s.site_id}</span> <span className="text-gray-500">{s.name}</span></h1>
        <p className="text-sm text-gray-600">{s.subjects} subjects · rule score <b>{s.rule_score.toFixed(0)}</b>{s.model_score !== null && <> · model score <b>{s.model_score.toFixed(0)}</b></>} · as of {s.as_of}</p>
        <p className="mt-1 space-x-3 text-sm"><button className="text-teal-700 hover:underline" onClick={openScorecard}>Scorecard (PDF)</button><Link className="text-teal-700 hover:underline" href="/sites/visit-plan">Monitoring plan</Link></p>
      </div>
      {s.model && (
        <section>
          <h2 className="mb-2">Model score</h2>
          <p className="text-sm text-gray-600">A model trained on simulated sites scores this site <b>{s.model.score.toFixed(0)}</b> out of 100. Closest pattern: {s.model.pattern_label}. This is a reason to look, not a conclusion.</p>
          {s.model.contributions.length > 0 && <ul className="mt-1 list-disc pl-5 text-sm text-gray-600">{s.model.contributions.map((c) => (
            <li key={c.feature}>{c.label}: {c.z.toFixed(1)} robust z-scores from the typical site; without it the score would be {c.effect.toFixed(0)} points lower.</li>))}</ul>}
        </section>
      )}
      <section>
        <h2 className="mb-2">Reasons to look</h2>
        {s.explanations.length === 0 ? <p className="text-sm text-gray-500">Nothing stands out against the rest of the study.</p> : (
          <ul className="space-y-1 text-sm">{s.explanations.map((e, i) => (<li key={i} className="flex gap-2"><RagDot rag={e.level} /><span>{e.text}</span></li>))}</ul>
        )}
      </section>
      <div className="grid gap-4 md:grid-cols-2">
        <section>
          <h2 className="mb-2">Last digit of blood pressure readings</h2>
          {digits ? (
            <div className="h-40"><ResponsiveContainer><BarChart data={digits.map((n, d) => ({ digit: d, n }))}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="digit" /><YAxis width={30} /><Tooltip />
              <ReferenceLine y={digits.reduce((a, b) => a + b, 0) / 10} stroke="#6b7280" strokeDasharray="4 2" /><Bar dataKey="n" fill="#2563eb" /></BarChart></ResponsiveContainer></div>
          ) : <p className="text-sm text-gray-500">Not enough readings yet.</p>}
          <p className="text-xs text-gray-500">Dashed line = count expected if all digits were equally common.{variance !== undefined && ` Pulse variability is ${variance.toFixed(2)} times the study average.`}</p>
        </section>
        <section>
          <h2 className="mb-2">Rule score over time</h2>
          <div className="h-40"><ResponsiveContainer><LineChart data={s.history}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={40} />
            <YAxis domain={[0, 100]} width={30} /><Tooltip /><Line dataKey="rule_score" stroke="#d97706" dot={false} strokeWidth={2} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
        </section>
      </div>
      <section>
        <h2 className="mb-2">Key risk indicators</h2>
        <table className="text-sm">
          <thead className="text-left text-gray-500"><tr><th className="pr-4"></th><th className="pr-4">Indicator</th><th className="pr-4">Value</th><th className="pr-4">Comparator</th><th>Rule</th></tr></thead>
          <tbody>{Object.entries(s.kri_defs).map(([k, d]) => { const c = s.kris[k]; return (
            <tr key={k}><td className="pr-4"><RagDot rag={c?.rag ?? "na"} /></td><td className="pr-4">{d.label}</td><td className="pr-4 font-mono">{c?.value?.toFixed(2) ?? "—"}</td>
              <td className="pr-4 font-mono">{c?.comparator?.toFixed(2) ?? "—"}</td><td className="text-gray-500">{d.rule}</td></tr>); })}</tbody>
        </table>
      </section>
      <section>
        <h2 className="mb-2">Issues ({s.issues.filter((i) => i.status !== "closed").length} open)</h2>
        {s.issues.length === 0 ? <p className="text-sm text-gray-500">No issues. Approving an agenda or a letter on the monitoring plan opens them.</p> : (
          <table className="text-sm">
            <thead className="text-left text-gray-500"><tr><th className="pr-4">Issue</th><th className="pr-4">From</th><th className="pr-4">Status</th><th className="pr-4">Owner</th><th className="pr-4">Opened</th><th className="pr-4">Closed</th><th></th></tr></thead>
            <tbody>{s.issues.map((i) => (
              <tr key={i.id} className="border-t"><td className="pr-4">{i.title}</td><td className="pr-4">{i.source}</td><td className="pr-4">{i.status.replace("_", " ")}</td><td className="pr-4">{i.owner ?? "—"}</td><td className="pr-4">{i.opened}</td><td className="pr-4">{i.closed ?? "—"}</td>
                <td>{canAct && (i.status === "closed"
                  ? <button className="text-xs text-teal-700 hover:underline" onClick={() => setStatus.mutate({ issue: i.id, status: "open" })}>Reopen</button>
                  : <button className="text-xs text-teal-700 hover:underline" onClick={() => setStatus.mutate({ issue: i.id, status: "closed" })}>Close</button>)}</td></tr>))}</tbody>
          </table>
        )}
        {setStatus.error && <p className="text-sm text-red-700">{(setStatus.error as Error).message}</p>}
      </section>
      {s.open_queries && <p className="text-sm text-gray-600">Open queries: {String(s.open_queries.open)} (older than 30 days: {String(s.open_queries[">30"])}).</p>}
    </main>
  );
}
