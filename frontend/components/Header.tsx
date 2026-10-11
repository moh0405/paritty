"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, ROLES, type Clock, type Job, type Role } from "@/lib/api";
import { useRole } from "./Providers";

export function Header() {
  const { role, setRole } = useRole();
  const qc = useQueryClient();
  const [auto, setAuto] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const health = useQuery({
    queryKey: ["health", role],
    queryFn: () => api<{ status: string; db: boolean }>("/health", role),
    refetchInterval: 15000,
  });
  const clock = useQuery({ queryKey: ["clock"], queryFn: () => api<Clock>("/sim/clock", role) });

  async function advance(days: number) {
    setError(null);
    try {
      const { job_id } = await api<{ job_id: string }>("/sim/advance", role, {
        method: "POST",
        body: JSON.stringify({ days, auto_approve: auto }),
      });
      let j: Job;
      do {
        await new Promise((r) => setTimeout(r, 300));
        j = await api<Job>(`/jobs/${job_id}`, role);
        setJob(j);
      } while (j.status === "running");
      if (j.status === "failed") setError(j.error);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setJob(null);
      await qc.invalidateQueries();
    }
  }

  const busy = job !== null;
  const unblinded = role === "unblinded_statistician";
  return (
    <header className="border-b">
      {unblinded && (
        <div className="bg-red-600 px-4 py-1 text-center text-sm font-medium text-white">
          UNBLINDED VIEW — access is audit-logged
        </div>
      )}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3">
        <Link href="/" className="font-semibold">LockStep</Link>
        <nav className="flex gap-3 text-sm text-gray-600">
          <Link href="/">Readiness</Link>
          <Link href="/queries">Queries</Link>
          <Link href="/checks">Checks</Link>
          <Link href="/recon/sae">SAE recon</Link>
          <Link href="/recon/labs">Lab recon</Link>
          <Link href="/medical">Medical</Link>
          <Link href="/sites">Sites</Link>
          <Link href="/hub">Hub</Link>
          <Link href="/evals">Evals</Link>
          <Link href="/medical/liver">Liver</Link>
          <Link href="/search">Term search</Link>
        </nav>
        <span className="text-sm text-gray-500">
          API: {health.data ? (health.data.db ? "ok" : "no database") : "unreachable"}
        </span>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-sm">
          <span className="font-mono">
            {clock.data ? `${clock.data.today} · day ${clock.data.study_day}` : "—"}
          </span>
          {[1, 7, 30].map((d) => (
            <button key={d} disabled={busy} onClick={() => advance(d)}
              className="rounded border px-2 py-1 hover:bg-gray-100 disabled:opacity-50">
              +{d}d
            </button>
          ))}
          <label className="flex items-center gap-1" title="A simulated data manager approves drafts and accepts explanations (logged as sim:auto)">
            <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> auto-approve
          </label>
          {busy && <span className="text-gray-500">running {job.done}/{job.total}…</span>}
          <label>
            Role{" "}
            <select className="rounded border px-2 py-1" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (<option key={r} value={r}>{r}</option>))}
            </select>
          </label>
        </div>
      </div>
      {error && <div className="bg-amber-100 px-4 py-1 text-sm text-amber-900">{error}</div>}
    </header>
  );
}
