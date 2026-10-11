"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type BacktestRun, type Job, type WhatIfResult } from "@/lib/api";
import { useRole } from "./Providers";

const CATEGORIES: Array<[string, string]> = [["sae_recon", "Serious adverse event reconciliation is finished"], ["lab_recon", "Lab reconciliation is finished"],
  ["expected", "No new queries arise from the visits still to come"], ["safety", "All open safety queries are closed"]];

export function WhatIf({ sites }: { sites: string[] }) {
  const { role } = useRole();
  const [site, setSite] = useState("");
  const [days, setDays] = useState(3);
  const [cats, setCats] = useState<string[]>([]);
  const run = useMutation({
    mutationFn: () => api<WhatIfResult>("/lock/whatif", role, { method: "POST", body: JSON.stringify({ site_response_days: site ? { [site]: days } : {}, close_categories: cats }) }),
  });
  const r = run.data;
  return (
    <section className="rounded border p-3">
      <h2 className="mb-1 font-medium">What if…?</h2>
      <p className="mb-2 text-sm text-gray-500">Test a change without touching any data. The same simulated futures are used with and without the change, so the difference is the effect of the change alone. A change can only speed things up.</p>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <label>Site <select className="rounded border px-2 py-1" value={site} onChange={(e) => setSite(e.target.value)}><option value="">no change</option>{sites.map((s) => (<option key={s}>{s}</option>))}</select></label>
        {site && <label>answers queries in about <input type="number" min={1} max={60} className="w-16 rounded border px-1 py-1" value={days} onChange={(e) => setDays(Number(e.target.value))} /> days</label>}
      </div>
      <div className="mt-2 space-y-0.5 text-sm">{CATEGORIES.map(([k, label]) => (
        <label key={k} className="flex items-center gap-2"><input type="checkbox" checked={cats.includes(k)} onChange={(e) => setCats(e.target.checked ? [...cats, k] : cats.filter((c) => c !== k))} />{label}</label>))}</div>
      <button className="mt-2 rounded border px-3 py-1 text-sm hover:bg-gray-100 disabled:opacity-50" disabled={run.isPending || (!site && cats.length === 0)} onClick={() => run.mutate()}>{run.isPending ? "Simulating…" : "Run what-if"}</button>
      {run.error && <p className="mt-1 text-sm text-red-700">{(run.error as Error).message}</p>}
      {r && (
        <div className="mt-3 rounded bg-gray-50 p-2 text-sm">
          <p className="font-medium">{r.description}</p>
          <table className="mt-1"><thead className="text-left text-gray-500"><tr><th className="pr-4"></th><th className="pr-4">Earliest (P10)</th><th className="pr-4">Most likely (P50)</th><th>Latest (P90)</th></tr></thead>
            <tbody><tr><td className="pr-4">Now</td><td className="pr-4 font-mono">{r.baseline.p10}</td><td className="pr-4 font-mono">{r.baseline.p50}</td><td className="font-mono">{r.baseline.p90}</td></tr>
              <tr><td className="pr-4">With the change</td><td className="pr-4 font-mono">{r.what_if.p10}</td><td className="pr-4 font-mono">{r.what_if.p50}</td><td className="font-mono">{r.what_if.p90}</td></tr></tbody></table>
          <p className="mt-1">{r.delta_p50_days === 0 ? "No change to the most likely lock date: something else is the constraint." : `The most likely lock date moves ${Math.abs(r.delta_p50_days)} days earlier.`}</p>
        </div>)}
    </section>
  );
}

export function Backtest() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [day, setDay] = useState(120);
  const runs = useQuery({ queryKey: ["backtests", role], queryFn: () => api<BacktestRun[]>("/lock/backtests", role) });
  const start = useMutation({
    mutationFn: async () => {
      const { job_id } = await api<{ job_id: string }>("/lock/backtest", role, { method: "POST", body: JSON.stringify({ at_day: day }) });
      let j: Job;
      let n = 0;
      do { await new Promise((r) => setTimeout(r, 2000)); j = await api<Job>(`/jobs/${job_id}`, role); n += 1; } while (j.status === "running" && n < 300);
      if (j.status === "failed") throw new Error(j.error ?? "backtest failed");
    },
    onSettled: () => qc.invalidateQueries({ queryKey: ["backtests"] }),
  });
  const latest = runs.data?.find((r) => r.status === "done");
  return (
    <section className="rounded border p-3">
      <h2 className="mb-1 font-medium">How good were past forecasts?</h2>
      <p className="mb-2 text-sm text-gray-500">A backtest copies the database, simulates to the chosen study day, records the forecast, then simulates to the end and compares it with when the work actually finished. It takes a minute or two.</p>
      <div className="flex items-center gap-2 text-sm">
        <label>Forecast made on study day <input type="number" min={61} max={400} className="w-20 rounded border px-1 py-1" value={day} onChange={(e) => setDay(Number(e.target.value))} /></label>
        <button className="rounded border px-3 py-1 hover:bg-gray-100 disabled:opacity-50" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Running…" : "Run backtest"}</button>
        {start.error && <span className="text-red-700">{(start.error as Error).message}</span>}
      </div>
      {latest && (
        <div className="mt-3 text-sm">
          <p>Forecast on {latest.forecast_day}: most likely <b>{latest.p50}</b>; the work actually finished with lock-ready on <b>{latest.actual_lock}</b> — off by <b>{latest.metrics.abs_error_days} days</b>{latest.metrics.p10_p90_covered ? ", inside the P10–P90 range" : ", outside the P10–P90 range"}.</p>
          {latest.checkpoints.length > 0 && (
            <table className="mt-2"><thead className="text-left text-gray-500"><tr><th className="pr-4">Forecast made</th><th className="pr-4">Days before lock</th><th className="pr-4">Most likely</th><th className="pr-4">Error (days)</th><th>In range</th></tr></thead>
              <tbody>{latest.checkpoints.map((c) => (<tr key={c.forecast_date}><td className="pr-4 font-mono">{c.forecast_date}</td><td className="pr-4">{c.days_before_lock}</td><td className="pr-4 font-mono">{c.p50}</td><td className={`pr-4 font-mono ${Math.abs(c.error_days) > 30 ? "text-amber-700" : ""}`}>{c.error_days > 0 ? "+" : ""}{c.error_days}</td><td>{c.covered ? "yes" : "no"}</td></tr>))}</tbody></table>)}
          <p className="mt-1 text-xs text-gray-500">Positive error = the forecast was later than what happened.</p>
        </div>)}
    </section>
  );
}
