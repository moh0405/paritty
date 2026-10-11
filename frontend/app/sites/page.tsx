"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis } from "recharts";
import { RagDot } from "@/components/Rag";
import { useRole } from "@/components/Providers";
import { api, type SiteDetail, type SitesList } from "@/lib/api";

const scorePill = (v: number | null) => v === null ? "bg-gray-100 text-gray-400" : v >= 75 ? "bg-red-100 text-red-700" : v >= 55 ? "bg-orange-100 text-orange-700" : v >= 35 ? "bg-amber-100 text-amber-700" : "bg-green-100 text-green-700";
const headLabel = (l: string) => l.replace(/\s*\(.*\)/, "");

export default function SitesPage() {
  const { role } = useRole();
  const [picked, setPicked] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["sites", role], queryFn: () => api<SitesList>("/sites", role) });
  const defs = q.data?.kri_defs ?? {};
  const keys = Object.keys(defs);
  const sites = [...(q.data?.sites ?? [])].sort((a, b) => b.rule_score - a.rule_score);
  const sel = picked ?? sites[0]?.site_id ?? null;
  const detail = useQuery({ queryKey: ["site", sel, role], enabled: !!sel, queryFn: () => api<SiteDetail>(`/sites/${sel}`, role) });
  const d = detail.data;
  const digits = d?.anomalies.find((a) => a.test === "terminal_digit")?.detail.digit_counts as number[] | undefined;
  const topReason = (s: (typeof sites)[number]) => {
    const red = keys.filter((k) => s.kris[k]?.rag === "red").map((k) => headLabel(defs[k].label));
    const amber = keys.filter((k) => s.kris[k]?.rag === "amber").map((k) => headLabel(defs[k].label));
    const r = (red.length ? red : amber).slice(0, 2);
    return r.length ? r.join(", ") : "No flags";
  };
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>Site risk</h1>
        <p className="mt-1 text-sm text-gray-500">Rule score and model score side by side{q.data?.as_of ? ` (as of ${q.data.as_of})` : ""}. Flags describe patterns that need a look, not conclusions. The model score comes from a model trained on simulated sites. <Link className="text-blue-700 hover:underline" href="/sites/visit-plan">Monitoring plan</Link></p>
      </div>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      <section className="overflow-x-auto !p-0">
        <table className="w-full min-w-[900px] text-sm">
          <thead><tr className="text-left"><th className="px-5 py-3">Site</th><th>Rule</th><th>Model</th>
            {keys.map((k) => (<th key={k} className="px-2 text-center normal-case tracking-normal" title={defs[k].rule}>{headLabel(defs[k].label)}</th>))}<th className="pr-5">Top reason</th></tr></thead>
          <tbody>
            {sites.map((s) => (
              <tr key={s.site_id} onClick={() => setPicked(s.site_id)} className={`cursor-pointer border-t ${sel === s.site_id ? "bg-blue-50/60" : "hover:bg-gray-50"}`}>
                <td className="px-5 py-3.5"><Link className="font-semibold hover:underline" href={`/sites/${s.site_id}`} onClick={(e) => e.stopPropagation()}>Site {s.site_id}</Link> <span className="text-gray-500">{s.name}</span></td>
                <td><span className={`rounded-md px-2.5 py-1 font-semibold ${scorePill(s.rule_score)}`}>{s.rule_score.toFixed(0)}</span></td>
                <td><span className={`rounded-md px-2.5 py-1 font-semibold ${scorePill(s.model_score)}`}>{s.model_score === null ? "-" : s.model_score.toFixed(0)}</span></td>
                {keys.map((k) => (<td key={k} className="px-2 text-center"><span className="inline-block scale-125"><RagDot rag={s.kris[k]?.rag ?? "na"} title={`${defs[k].label}: ${s.kris[k]?.value?.toFixed(2) ?? "n/a"} (comparison ${s.kris[k]?.comparator?.toFixed(2) ?? "n/a"})`} /></span></td>))}
                <td className="pr-5 text-gray-500">{topReason(s)}</td>
              </tr>
            ))}
            {sites.length === 0 && <tr><td colSpan={4 + keys.length} className="p-5 text-gray-500">No site data yet. Advance the clock.</td></tr>}
          </tbody>
        </table>
        <p className="border-t px-5 py-3 text-xs text-gray-500">Dots show KRI status: red, amber, green. Hover a dot for the value and the comparison group. Click a row to see why it was flagged.</p>
      </section>

      {d && (
        <div className="grid gap-5 lg:grid-cols-3">
          <section>
            <h2>Site {d.site_id} why flagged</h2>
            {d.explanations.length === 0 ? <p className="mt-3 text-sm text-gray-500">Nothing stands out against the rest of the study.</p> : (
              <ul className="mt-3 space-y-3 text-sm">{d.explanations.slice(0, 5).map((e, i) => (<li key={i} className="flex gap-2"><span className="mt-1"><RagDot rag={e.level} /></span><span>{e.text}</span></li>))}</ul>)}
            {d.open_queries && <p className="mt-3 text-xs text-gray-500">Open queries: {String(d.open_queries.open)} (older than 30 days: {String(d.open_queries[">30"])}).</p>}
            {d.rule_score >= 75 && <span className="mt-3 inline-block rounded-full bg-red-100 px-3 py-1 text-xs font-semibold text-red-700">Visit recommended</span>}
          </section>
          <section>
            <h2>Vitals digit check, site {d.site_id}</h2>
            <p className="mt-2 text-sm font-semibold">Last digit of systolic BP</p>
            {digits ? (<>
              <div className="mt-2 h-36"><ResponsiveContainer><BarChart data={digits.map((n, i) => ({ digit: i, n }))}><XAxis dataKey="digit" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip cursor={false} />
                <Bar dataKey="n" fill="#bfdbfe" radius={[3, 3, 0, 0]} shape={(p: { x?: number; y?: number; width?: number; height?: number; payload?: { n: number } }) => { const avg = digits.reduce((a, b) => a + b, 0) / 10; const hot = (p.payload?.n ?? 0) > avg * 1.6; return <rect x={p.x} y={p.y} width={p.width} height={p.height} rx={3} fill={hot ? "#2563eb" : "#bfdbfe"} />; }} /></BarChart></ResponsiveContainer></div>
              <p className="text-xs text-gray-500">Digits far above the even share are shaded dark. Needs review, not a conclusion.</p></>) : <p className="mt-2 text-sm text-gray-500">Not enough readings yet.</p>}
          </section>
          <section>
            <h2>Indicators vs study</h2>
            <ul className="mt-3 space-y-3 text-sm">{Object.entries(d.kri_defs).map(([k, def]) => { const c = d.kris[k]; const max = Math.max(c?.value ?? 0, c?.comparator ?? 0, 0.0001); return (
              <li key={k}><div className="flex justify-between"><span>{headLabel(def.label)}</span><span className="font-mono text-xs text-gray-500">{c?.value?.toFixed(1) ?? "-"} vs {c?.comparator?.toFixed(1) ?? "-"}</span></div>
                <div className="mt-1 h-2 rounded-full bg-gray-100"><div className={`h-2 rounded-full ${c?.rag === "red" ? "bg-red-500" : c?.rag === "amber" ? "bg-amber-400" : "bg-blue-600"}`} style={{ width: `${(100 * (c?.value ?? 0)) / max}%` }} /></div></li>); })}</ul>
          </section>
        </div>
      )}
    </main>
  );
}
