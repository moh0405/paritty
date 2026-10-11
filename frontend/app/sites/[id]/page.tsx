"use client";
import { useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { RagDot } from "@/components/Rag";
import { useRole } from "@/components/Providers";
import { api, type SiteDetail } from "@/lib/api";

export default function SitePage() {
  const { id } = useParams<{ id: string }>();
  const { role } = useRole();
  const q = useQuery({ queryKey: ["site", id, role], queryFn: () => api<SiteDetail>(`/sites/${id}`, role) });
  if (q.error) return <main className="p-6 text-red-700">{(q.error as Error).message}</main>;
  if (!q.data) return <main className="p-6 text-gray-500">Loading…</main>;
  const s = q.data;
  const digits = s.anomalies.find((a) => a.test === "terminal_digit")?.detail.digit_counts as number[] | undefined;
  const variance = s.anomalies.find((a) => a.test === "variance_ratio")?.detail.ratio as number | undefined;
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1 className="text-xl font-semibold">Site <span className="font-mono">{s.site_id}</span> <span className="text-gray-500">{s.name}</span></h1>
        <p className="text-sm text-gray-600">{s.subjects} subjects · rule score <b>{s.rule_score.toFixed(0)}</b> · as of {s.as_of}</p>
      </div>
      <section>
        <h2 className="mb-1 font-medium">Reasons to look</h2>
        {s.explanations.length === 0 ? <p className="text-sm text-gray-500">Nothing stands out against the rest of the study.</p> : (
          <ul className="space-y-1 text-sm">{s.explanations.map((e, i) => (<li key={i} className="flex gap-2"><RagDot rag={e.level} /><span>{e.text}</span></li>))}</ul>
        )}
      </section>
      <div className="grid gap-4 md:grid-cols-2">
        <section className="rounded border p-3">
          <h2 className="mb-1 font-medium">Last digit of blood pressure readings</h2>
          {digits ? (
            <div className="h-40"><ResponsiveContainer><BarChart data={digits.map((n, d) => ({ digit: d, n }))}>
              <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="digit" /><YAxis width={30} /><Tooltip />
              <ReferenceLine y={digits.reduce((a, b) => a + b, 0) / 10} stroke="#6b7280" strokeDasharray="4 2" /><Bar dataKey="n" fill="#2563eb" /></BarChart></ResponsiveContainer></div>
          ) : <p className="text-sm text-gray-500">Not enough readings yet.</p>}
          <p className="text-xs text-gray-500">Dashed line = count expected if all digits were equally common.{variance !== undefined && ` Pulse variability is ${variance.toFixed(2)} times the study average.`}</p>
        </section>
        <section className="rounded border p-3">
          <h2 className="mb-1 font-medium">Rule score over time</h2>
          <div className="h-40"><ResponsiveContainer><LineChart data={s.history}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={40} />
            <YAxis domain={[0, 100]} width={30} /><Tooltip /><Line dataKey="rule_score" stroke="#d97706" dot={false} strokeWidth={2} isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
        </section>
      </div>
      <section>
        <h2 className="mb-1 font-medium">Key risk indicators</h2>
        <table className="text-sm">
          <thead className="text-left text-gray-500"><tr><th className="pr-4"></th><th className="pr-4">Indicator</th><th className="pr-4">Value</th><th className="pr-4">Comparator</th><th>Rule</th></tr></thead>
          <tbody>{Object.entries(s.kri_defs).map(([k, d]) => { const c = s.kris[k]; return (
            <tr key={k}><td className="pr-4"><RagDot rag={c?.rag ?? "na"} /></td><td className="pr-4">{d.label}</td><td className="pr-4 font-mono">{c?.value?.toFixed(2) ?? "—"}</td>
              <td className="pr-4 font-mono">{c?.comparator?.toFixed(2) ?? "—"}</td><td className="text-gray-500">{d.rule}</td></tr>); })}</tbody>
        </table>
      </section>
      {s.open_queries && <p className="text-sm text-gray-600">Open queries: {String(s.open_queries.open)} (older than 30 days: {String(s.open_queries[">30"])}).</p>}
    </main>
  );
}
