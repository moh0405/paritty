"use client";
import { useQuery } from "@tanstack/react-query";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Backtest, WhatIf } from "@/components/ForecastTools";
import { useRole } from "@/components/Providers";
import { api, type ForecastPoint, type LockForecast } from "@/lib/api";

const DAY = 86400000;
const days = (a: string, b: string) => Math.round((Date.parse(b) - Date.parse(a)) / DAY);
const nice = (iso: string) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric", timeZone: "UTC" });
const short = (iso: string) => new Date(iso + "T00:00:00Z").toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });

function RangeBar({ p10, p50, p90 }: { p10: string; p50: string; p90: string }) {
  const lo = Date.parse(p10), hi = Date.parse(p90), mid = Date.parse(p50);
  const pad = Math.max((hi - lo) * 0.6, DAY), a = lo - pad, b = hi + pad;
  const pos = (t: number) => `${(100 * (t - a)) / (b - a)}%`;
  return (
    <div className="mt-6">
      <div className="relative h-2 rounded-full bg-gray-200">
        <div className="absolute h-2 rounded-full bg-blue-300" style={{ left: pos(lo), width: `${(100 * (hi - lo)) / (b - a)}%` }} />
        <div className="absolute -top-1.5 h-5 w-5 -translate-x-1/2 rounded-full bg-blue-600 ring-4 ring-white" style={{ left: pos(mid) }} />
      </div>
      <div className="relative mt-2 h-4 text-xs text-gray-500">
        <span className="absolute -translate-x-1/2" style={{ left: pos(lo) }}>P10</span>
        <span className="absolute -translate-x-1/2 font-semibold text-blue-700" style={{ left: pos(mid) }}>P50</span>
        <span className="absolute -translate-x-1/2" style={{ left: pos(hi) }}>P90</span>
      </div>
    </div>
  );
}

export default function Home() {
  const { role } = useRole();
  const f = useQuery({ queryKey: ["lock", role], queryFn: () => api<LockForecast>("/lock/forecast", role) });
  const h = useQuery({ queryKey: ["lock-history", role], queryFn: () => api<ForecastPoint[]>("/lock/forecast/history", role) });
  const sites = useQuery({ queryKey: ["whatif-sites", role], queryFn: () => api<{ sites: Array<{ site_id: string }> }>("/sites", role) });
  if (f.error) return <main className="p-6 text-red-700">{(f.error as Error).message}</main>;
  if (!f.data) return <main className="p-6 text-gray-500">Loading…</main>;
  const d = f.data, r = d.readiness, b = r.benchmark;
  const chart = (h.data ?? []).map((p) => ({ day: p.day, band: [Date.parse(p.p10) / DAY, Date.parse(p.p90) / DAY], med: Date.parse(p.p50) / DAY }));
  const fmt = (v: number) => short(new Date(v * DAY).toISOString().slice(0, 10));
  const bench = Math.min(100, (100 * b.days_lplv_to_p50) / Math.max(b.tufts_days, 1));
  const maxBlock = Math.max(1, ...d.blockers.map((x) => Math.abs(x.delta_p50_days)));
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>Lock readiness</h1>
        <p className="mt-1 text-sm text-gray-500">Forecast refreshes after every daily cycle. Every number links to its source rows.</p>
      </div>

      <div className="grid gap-5 lg:grid-cols-3">
        <section>
          <h2>Predicted database lock (P50)</h2>
          <div className="mt-2 text-5xl font-bold tracking-tight">{nice(d.p50)}</div>
          <p className="mt-2 text-sm text-gray-500">Likely range {short(d.p10)} to {short(d.p90)} <span className="text-gray-400">(P10 to P90, {d.n_sims.toLocaleString()} simulations)</span></p>
          <p className="text-sm text-gray-500">{days(d.sim_date, d.p50)} days from today ({d.sim_date})</p>
          <RangeBar p10={d.p10} p50={d.p50} p90={d.p90} />
          {r.enrollment && <p className="mt-3 text-xs text-gray-500">Enrolment {r.enrollment.enrolled} of {r.enrollment.planned} planned, about {(r.enrollment.rate_per_day * 7).toFixed(1)} per week recently.</p>}
        </section>

        <section>
          <h2>Vs benchmark</h2>
          <div className={`mt-2 text-5xl font-bold tracking-tight ${b.days_lplv_to_p50 <= b.tufts_days ? "text-green-600" : "text-red-600"}`}>{b.days_lplv_to_p50} days</div>
          <p className="mt-2 text-sm text-gray-500">Last patient last visit (about {b.lplv}) to P50 lock</p>
          <p className="mt-3 text-sm font-semibold">Tufts benchmark: {b.tufts_days} days</p>
          <div className="mt-2 h-2.5 rounded-full bg-gray-200"><div className={`h-2.5 rounded-full ${b.days_lplv_to_p50 <= b.tufts_days ? "bg-green-500" : "bg-red-500"}`} style={{ width: `${bench}%` }} /></div>
        </section>

        <WhatIf sites={(sites.data?.sites ?? []).map((x) => x.site_id).sort()} />
      </div>

      <div className="grid gap-5 lg:grid-cols-[1fr_1.15fr]">
        <section>
          <h2>Readiness checklist <span className="font-normal normal-case tracking-normal text-gray-400">({r.met} of {r.total} met)</span></h2>
          <ul className="mt-3 divide-y text-sm">{r.criteria.map((c) => (
            <li key={c.key} className="flex items-center gap-3 py-3">
              <span className={`h-3 w-3 shrink-0 rounded-full ${c.met ? "bg-green-500" : "bg-amber-500"}`} />
              <span className="flex-1"><span className="font-medium">{c.label}</span><span className="block text-xs text-gray-500">{c.detail}</span></span>
              <span className={`text-xs font-semibold ${c.met ? "text-green-600" : "text-amber-600"}`}>{c.met ? "Met" : "Open"}</span>
            </li>))}</ul>
          <p className="mt-3 text-xs text-gray-500">Open critical items block lock until closed.</p>
        </section>

        <div className="space-y-5">
          <section>
            <h2>Top blockers <span className="font-normal normal-case tracking-normal text-gray-400">(change in P50 if resolved)</span></h2>
            {d.blockers.length === 0 ? <p className="mt-2 text-sm text-gray-500">No single site or category stands out.</p> : (
              <ul className="mt-3 space-y-3 text-sm">{d.blockers.map((x) => (
                <li key={`${x.type}${x.id}`}>
                  <div className="flex items-center gap-2"><span className="flex-1">{x.type === "site" ? `Site ${x.id}` : x.id.replace(/_/g, " ")}</span>
                    <span className="rounded-full bg-indigo-50 px-2 py-0.5 text-xs font-medium text-indigo-700">{x.items} rows</span>
                    <span className="w-20 text-right font-semibold text-green-600">-{Math.abs(x.delta_p50_days)} days</span></div>
                  <div className="mt-1 h-2 rounded-full bg-gray-100"><div className="h-2 rounded-full bg-blue-600" style={{ width: `${(100 * Math.abs(x.delta_p50_days)) / maxBlock}%` }} /></div>
                </li>))}</ul>)}
          </section>
          <section>
            <h2>Forecast history <span className="font-normal normal-case tracking-normal text-gray-400">(P10 to P90 band, P50 line)</span></h2>
            {chart.length > 1 ? (
              <div className="mt-2 h-52"><ResponsiveContainer><ComposedChart data={chart}>
                <CartesianGrid stroke="#eef0f3" vertical={false} /><XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={50} /><YAxis domain={["auto", "auto"]} tickFormatter={fmt} width={56} tick={{ fontSize: 10 }} />
                <Tooltip formatter={(v) => (Array.isArray(v) ? `${fmt(v[0])} to ${fmt(v[1])}` : fmt(Number(v)))} />
                <Area dataKey="band" stroke="none" fill="#bfdbfe" fillOpacity={0.6} isAnimationActive={false} name="P10 to P90" />
                <Line dataKey="med" stroke="#2563eb" strokeWidth={2} dot={false} isAnimationActive={false} name="P50" />
              </ComposedChart></ResponsiveContainer></div>
            ) : <p className="mt-2 text-sm text-gray-500">Advance the clock to build a forecast history.</p>}
          </section>
        </div>
      </div>
      <Backtest />
    </main>
  );
}
