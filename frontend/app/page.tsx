"use client";
import { useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Backtest, WhatIf } from "@/components/ForecastTools";
import { useRole } from "@/components/Providers";
import { api, type ForecastPoint, type LockForecast } from "@/lib/api";

const days = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / 86400000);

export default function Home() {
  const { role } = useRole();
  const f = useQuery({ queryKey: ["lock", role], queryFn: () => api<LockForecast>("/lock/forecast", role) });
  const h = useQuery({ queryKey: ["lock-history", role], queryFn: () => api<ForecastPoint[]>("/lock/forecast/history", role) });
  const sites = useQuery({ queryKey: ["whatif-sites", role], queryFn: () => api<{ sites: Array<{ site_id: string }> }>("/sites", role) });
  if (f.error) return <main className="p-6 text-red-700">{(f.error as Error).message}</main>;
  if (!f.data) return <main className="p-6 text-gray-500">Loading…</main>;
  const d = f.data, r = d.readiness, b = r.benchmark;
  const chart = (h.data ?? []).map((p) => ({ day: p.day, p10: Date.parse(p.p10) / 86400000, med: Date.parse(p.p50) / 86400000, p90: Date.parse(p.p90) / 86400000 }));
  const fmt = (v: number) => new Date(v * 86400000).toISOString().slice(0, 10);
  return (
    <main className="space-y-6 p-6">
      <section>
        <h1 className="text-xl font-semibold">Database lock readiness</h1>
        <div className="mt-2 flex flex-wrap items-end gap-6">
          <div><div className="text-sm text-gray-500">Most likely lock date (P50)</div><div className="text-4xl font-semibold">{d.p50}</div></div>
          <div className="text-sm text-gray-700">Likely range <b>{d.p10}</b> to <b>{d.p90}</b> (P10–P90, {d.n_sims} simulations)<br />
            {days(d.sim_date, d.p50)} days from today ({d.sim_date})</div>
          <div className="text-sm text-gray-700">Last patient last visit about <b>{b.lplv}</b>; lock {b.days_lplv_to_p50} days later against a {b.tufts_days}-day benchmark.</div>
        </div>
        {r.enrollment && <p className="mt-1 text-sm text-gray-500">Enrolment: {r.enrollment.enrolled} of {r.enrollment.planned} planned, about {(r.enrollment.rate_per_day * 7).toFixed(1)} per week recently.</p>}
      </section>

      <div className="grid gap-6 md:grid-cols-2">
        <section>
          <h2 className="mb-1 font-medium">Readiness checklist <span className="text-sm font-normal text-gray-500">({r.met} of {r.total} met)</span></h2>
          <ul className="space-y-1 text-sm">{r.criteria.map((c) => (
            <li key={c.key} className="flex gap-2"><span className={c.met ? "text-green-600" : "text-amber-600"}>{c.met ? "✓" : "○"}</span><span><b>{c.label}</b><br /><span className="text-gray-500">{c.detail}</span></span></li>))}</ul>
        </section>
        <section>
          <h2 className="mb-1 font-medium">What is holding the date back</h2>
          {d.blockers.length === 0 ? <p className="text-sm text-gray-500">No single site or category stands out.</p> : (
            <table className="text-sm"><thead className="text-left text-gray-500"><tr><th className="pr-4">Blocker</th><th className="pr-4">Items</th><th>Lock date moves earlier by</th></tr></thead>
              <tbody>{d.blockers.map((x) => (<tr key={`${x.type}${x.id}`}><td className="pr-4">{x.type === "site" ? `Site ${x.id}` : x.id.replace("_", " ")}</td><td className="pr-4">{x.items}</td><td className="font-mono">{x.delta_p50_days} days</td></tr>))}</tbody></table>)}
          <p className="mt-1 text-xs text-gray-500">Each figure is how much sooner the most likely date would be if that site, or that kind of work, were already finished.</p>
        </section>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <WhatIf sites={(sites.data?.sites ?? []).map((x) => x.site_id).sort()} />
        <Backtest />
      </div>

      <section>
        <h2 className="mb-1 font-medium">Forecast over time</h2>
        {chart.length > 1 ? (
          <div className="h-56 max-w-4xl"><ResponsiveContainer><LineChart data={chart}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={50} /><YAxis domain={["auto", "auto"]} tickFormatter={fmt} width={80} tick={{ fontSize: 10 }} />
            <Tooltip formatter={(v) => fmt(Number(v))} />
            <Line dataKey="p10" stroke="#93c5fd" dot={false} isAnimationActive={false} name="P10" /><Line dataKey="med" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false} name="P50" /><Line dataKey="p90" stroke="#93c5fd" dot={false} isAnimationActive={false} name="P90" />
          </LineChart></ResponsiveContainer></div>
        ) : <p className="text-sm text-gray-500">Advance the clock to build a forecast history.</p>}
      </section>
    </main>
  );
}
