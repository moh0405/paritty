"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useRole } from "@/components/Providers";
import { VerificationBadge } from "@/components/VerificationBadge";
import { api, type EvalCompare, type EvalDetail, type EvalRun, type EvalSummaryResult, type Job } from "@/lib/api";

const pct = (v: number | undefined) => (v === undefined ? "—" : v <= 1 ? `${(v * 100).toFixed(0)}%` : v.toFixed(2));

export default function EvalsPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [scenario, setScenario] = useState("smoke");
  const [repeats, setRepeats] = useState(1);
  const [selected, setSelected] = useState<string[]>([]);
  const [metric, setMetric] = useState("checks.recall");
  const [running, setRunning] = useState<string | null>(null);

  const scenarios = useQuery({ queryKey: ["eval-scenarios", role], queryFn: () => api<Array<{ name: string; advance_days: number; injections: Array<{ kind: string; count: number }> }>>("/eval/scenarios", role) });
  const runs = useQuery({ queryKey: ["eval-runs", role], queryFn: () => api<EvalRun[]>("/eval/runs", role), refetchInterval: running ? 3000 : false });
  const detail = useQuery({ queryKey: ["eval-run", selected[0], role], enabled: selected.length === 1, queryFn: () => api<EvalDetail>(`/eval/runs/${selected[0]}`, role) });
  const cmp = useQuery({ queryKey: ["eval-cmp", selected.join(), role], enabled: selected.length > 1, queryFn: () => api<EvalCompare>(`/eval/compare?ids=${selected.join(",")}`, role) });

  const start = useMutation({
    mutationFn: async () => {
      const { job_id } = await api<{ job_id: string }>("/eval/runs", role, { method: "POST", body: JSON.stringify({ scenario, repeats }) });
      setRunning(job_id);
      let j: Job;
      do { await new Promise((r) => setTimeout(r, 1500)); j = await api<Job>(`/jobs/${job_id}`, role); } while (j.status === "running");
      if (j.status === "failed") throw new Error(j.error ?? "run failed");
    },
    onSettled: () => { setRunning(null); qc.invalidateQueries({ queryKey: ["eval-runs"] }); },
  });
  const explain = useMutation({ mutationFn: (id: string) => api<EvalSummaryResult>(`/eval/runs/${id}/summary`, role, { method: "POST" }) });
  const trend = (runs.data ?? []).filter((r) => r.scenario === scenario && r.headline[metric] !== undefined).reverse().map((r, i) => ({ n: i + 1, v: r.headline[metric] }));
  const sel = scenarios.data?.find((s) => s.name === scenario);
  const toggle = (id: string) => setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id) : [...s, id].slice(-4)));

  return (
    <main className="space-y-5 p-6">
      <section>
        <h1 className="text-xl font-semibold">Evaluations</h1>
        <p className="text-sm text-gray-500">Each run forks the database, plants errors blindly, advances the simulation, and scores the detectors against what was planted. Findings that also appear on an un-injected control run are not counted as false alarms.</p>
        <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
          <select className="rounded border px-2 py-1" value={scenario} onChange={(e) => setScenario(e.target.value)}>{(scenarios.data ?? []).map((s) => (<option key={s.name}>{s.name}</option>))}</select>
          <label>repeats <input type="number" min={1} max={5} className="w-14 rounded border px-1 py-1" value={repeats} onChange={(e) => setRepeats(Number(e.target.value))} /></label>
          <button className="rounded border px-3 py-1 hover:bg-gray-100 disabled:opacity-50" disabled={start.isPending} onClick={() => start.mutate()}>{start.isPending ? "Running…" : "Run scenario"}</button>
          {start.error && <span className="text-red-700">{(start.error as Error).message}</span>}
          {sel && <span className="text-gray-500">{sel.advance_days} days · {sel.injections.map((i) => `${i.count}× ${i.kind}`).join(", ") || "no injections"}</span>}
        </div>
      </section>

      <section>
        <h2 className="mb-1 font-medium">Runs <span className="text-sm font-normal text-gray-500">(select up to 4 to compare)</span></h2>
        <table className="w-full text-sm">
          <thead className="text-left text-gray-500"><tr><th></th><th>Scenario</th><th>Status</th><th>Checks recall / precision</th><th>SAE recall / precision</th><th>Hy&apos;s Law recall</th><th>Sites recall@k</th><th>Grounding</th></tr></thead>
          <tbody>{(runs.data ?? []).map((r) => (
            <tr key={r.id} className="border-t"><td className="p-1"><input type="checkbox" checked={selected.includes(r.id)} onChange={() => toggle(r.id)} /></td>
              <td>{r.scenario} <span className="font-mono text-xs text-gray-400">{r.id.slice(0, 6)}</span></td><td>{r.status}</td>
              <td>{pct(r.headline["checks.recall"])} / {pct(r.headline["checks.precision"])}</td><td>{pct(r.headline["sae_recon.recall"])} / {pct(r.headline["sae_recon.precision"])}</td>
              <td>{pct(r.headline["medical.hys_law_recall"])}</td><td>{pct(r.headline["sites.rule_recall_at_k"])}</td><td>{pct(r.headline["system.grounding_rate"])}</td></tr>))}
            {runs.data?.length === 0 && <tr><td colSpan={8} className="p-3 text-gray-500">No runs yet.</td></tr>}</tbody>
        </table>
      </section>

      {detail.data && (
        <section>
          <h2 className="mb-1 font-medium">Run {detail.data.id.slice(0, 8)} — {detail.data.scenario}</h2>
          <div className="my-1 text-sm">
            <button className="rounded border px-3 py-1 hover:bg-gray-100 disabled:opacity-50" disabled={explain.isPending} onClick={() => explain.mutate(detail.data.id)}>{explain.isPending ? "Writing…" : "Explain this run in plain English"}</button>
            {explain.error && <span className="ml-2 text-red-700">{(explain.error as Error).message}</span>}
            {explain.data && explain.data.run_id === detail.data.id && (<div className="mt-2 max-w-3xl rounded bg-gray-50 p-3"><div className="mb-1 flex items-center gap-2"><VerificationBadge status={explain.data.verification_status} /><span className="text-xs text-gray-500">{explain.data.source === "gemini" ? "AI wording, every claim checked" : "built from the metrics, every claim checked"}</span></div><p>{explain.data.text}</p></div>)}
          </div>
          <p className="text-xs text-gray-500">seed {detail.data.seed} · planted {Object.entries(detail.data.planted).map(([k, n]) => `${n}× ${k}`).join(", ") || "none"}</p>
          <div className="mt-2 grid gap-3 md:grid-cols-3">
            {Object.entries(detail.data.metrics).map(([module, ms]) => (
              <div key={module} className="rounded border p-2"><h3 className="mb-1 text-sm font-medium">{module}</h3>
                <table className="text-xs"><tbody>{ms.map((m) => (<tr key={m.metric}><td className="pr-3 text-gray-600">{m.metric}</td><td className="font-mono">{m.value <= 1 && m.value >= 0 ? m.value.toFixed(3) : m.value.toFixed(1)}</td></tr>))}</tbody></table></div>))}
          </div>
        </section>
      )}
      {cmp.data && (
        <section>
          <h2 className="mb-1 font-medium">Comparison</h2>
          <table className="text-xs"><thead className="text-left text-gray-500"><tr><th className="pr-4">Metric</th>{cmp.data.runs.map((r) => (<th key={r} className="pr-4 font-mono">{r.slice(0, 6)}</th>))}</tr></thead>
            <tbody>{Object.entries(cmp.data.metrics).map(([m, v]) => (<tr key={m}><td className="pr-4">{m}</td>{cmp.data!.runs.map((r) => (<td key={r} className="pr-4 font-mono">{v[r] === undefined ? "—" : v[r].toFixed(3)}</td>))}</tr>))}</tbody></table>
        </section>
      )}
      <section>
        <h2 className="mb-1 font-medium">Trend <select className="ml-2 rounded border px-1 py-0.5 text-sm" value={metric} onChange={(e) => setMetric(e.target.value)}>
          {["checks.recall", "checks.precision", "sae_recon.recall", "sae_recon.precision", "medical.hys_law_recall", "sites.rule_recall_at_k", "system.grounding_rate"].map((m) => (<option key={m}>{m}</option>))}</select></h2>
        {trend.length > 1 ? <div className="h-40 max-w-xl"><ResponsiveContainer><LineChart data={trend}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="n" /><YAxis domain={[0, 1]} width={30} /><Tooltip /><Line dataKey="v" stroke="#2563eb" isAnimationActive={false} /></LineChart></ResponsiveContainer></div>
          : <p className="text-sm text-gray-500">Run this scenario at least twice to see a trend.</p>}
      </section>
    </main>
  );
}
