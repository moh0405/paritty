"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, ROLES, type Clock, type Job, type Role } from "@/lib/api";
import { useRole } from "./Providers";

const ROLE_LABEL: Record<string, string> = {
  data_manager: "Data manager", medical_monitor: "Medical monitor", central_monitor: "Central monitor",
  study_lead: "Study lead", unblinded_statistician: "Unblinded statistician", site_coordinator: "Site coordinator",
};

export function Header() {
  const { role, setRole } = useRole();
  const qc = useQueryClient();
  const [auto, setAuto] = useState(true);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const health = useQuery({ queryKey: ["health", role], queryFn: () => api<{ status: string; db: boolean }>("/health", role), refetchInterval: 15000 });
  const clock = useQuery({ queryKey: ["clock"], queryFn: () => api<Clock>("/sim/clock", role) });

  async function advance(days: number) {
    setError(null);
    try {
      const { job_id } = await api<{ job_id: string }>("/sim/advance", role, { method: "POST", body: JSON.stringify({ days, auto_approve: auto }) });
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
  const apiOk = health.data?.db;
  return (
    <header className="sticky top-0 z-20">
      <div className="flex flex-wrap items-center gap-3 bg-[#111827] px-5 py-3 text-sm text-white">
        <Link href="/" className="mr-2 text-xl font-semibold tracking-tight">LockStep</Link>
        <div className="rounded-md bg-[#1f2937] px-4 py-2 font-mono text-gray-100">
          {clock.data ? `Sim day ${clock.data.study_day}  |  ${clock.data.today}` : "Sim day —"}
        </div>
        <div className="flex gap-2">
          {[1, 7, 30].map((d) => (
            <button key={d} disabled={busy} onClick={() => advance(d)}
              className={`rounded-md px-3 py-1.5 font-medium disabled:opacity-50 ${d === 7 ? "bg-blue-600 hover:bg-blue-500" : "bg-[#374151] hover:bg-[#4b5563]"}`}>
              +{d} {d === 1 ? "day" : "days"}
            </button>
          ))}
        </div>
        <label className="flex items-center gap-1 text-gray-300" title="A simulated data manager approves drafts and accepts explanations (logged as sim:auto)">
          <input type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> auto-approve
        </label>
        {busy && <span className="text-gray-300">running {job.done}/{job.total}…</span>}
        <span className={`text-xs ${apiOk ? "text-gray-400" : "text-amber-300"}`}>API {health.data ? (apiOk ? "ok" : "no database") : "unreachable"}</span>
        <div className="ml-auto flex flex-wrap items-center gap-3">
          <label className="flex items-center gap-1 rounded-md bg-[#1f2937] px-3 py-1.5">Role:
            <select className="bg-transparent outline-none" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (<option key={r} value={r} className="text-black">{ROLE_LABEL[r] ?? r}</option>))}
            </select>
          </label>
          <span className="rounded-md bg-[#1f2937] px-3 py-1.5 text-gray-200">Sites: all 24</span>
          <span className={`rounded-md px-4 py-2 text-xs font-bold tracking-wide ${unblinded ? "bg-red-600" : "bg-emerald-700"}`}>
            {unblinded ? "UNBLINDED · AUDITED" : "BLINDED VIEW"}
          </span>
        </div>
      </div>
      {error && <div className="bg-amber-100 px-5 py-1 text-sm text-amber-900">{error}</div>}
    </header>
  );
}
