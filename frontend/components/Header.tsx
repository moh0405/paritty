"use client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { api, ROLES, type Clock, type Job, type Role } from "@/lib/api";
import { useRole } from "./Providers";
import { Badge } from "./ui/Badge";
import { Button } from "./ui/Button";
import { Icon } from "./ui/Icon";

const ROLE_LABEL: Record<string, string> = {
  data_manager: "Data manager", medical_monitor: "Medical monitor", central_monitor: "Central monitor",
  study_lead: "Study lead", unblinded_statistician: "Unblinded statistician", site_coordinator: "Site coordinator",
};

export function Header() {
  const { role, setRole } = useRole();
  const qc = useQueryClient();
  const [auto, setAuto] = useState(true);
  const [selectedDays, setSelectedDays] = useState(7);
  const [advancing, setAdvancing] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);

  const health = useQuery({ queryKey: ["health", role], queryFn: () => api<{ status: string; db: boolean }>("/health", role), refetchInterval: 15000 });
  const clock = useQuery({ queryKey: ["clock"], queryFn: () => api<Clock>("/sim/clock", role) });

  async function advance(days: number) {
    setSelectedDays(days);
    setAdvancing(true);
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
      setAdvancing(false);
      await qc.invalidateQueries();
    }
  }

  const busy = advancing;
  const unblinded = role === "unblinded_statistician";
  const apiOk = health.data?.db;
  return (
    <header className="sticky top-0 z-20 border-b border-slate-700/50 bg-[#0f1f2e]/95 text-white shadow-sm backdrop-blur-xl">
      <div className="flex min-h-16 flex-wrap items-center gap-2.5 px-4 py-2 text-sm sm:px-6">
        <Link href="/" className="mr-2 flex min-h-11 items-center gap-2.5 text-lg font-semibold tracking-tight">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-cyan-600 text-white shadow-lg shadow-cyan-950/30"><Icon name="activity" className="h-5 w-5" /></span>
          <span>Paritty</span>
        </Link>
        <div className="order-3 rounded-lg border border-white/10 bg-white/[.06] px-3 py-2 font-mono text-xs tabular-nums text-slate-200 sm:order-none">
          {clock.data ? <><span className="text-white">Day {clock.data.study_day}</span><span className="mx-2 text-slate-600">•</span>{clock.data.today}</> : "Sim day —"}
        </div>
        <div className="order-4 flex items-center gap-1 rounded-xl border border-white/10 bg-black/20 p-1 sm:order-none" role="group" aria-label="Days to advance">
          {[1, 7, 30].map((d) => (
            <Button key={d} disabled={busy} onClick={() => advance(d)} size="sm" variant="ghost" aria-pressed={selectedDays === d}
              className={selectedDays === d
                ? "bg-cyan-600 text-white shadow-sm hover:bg-cyan-500 hover:text-white"
                : "border border-transparent text-slate-400 hover:border-white/10 hover:bg-white/[.07] hover:text-white"}>
              +{d} {d === 1 ? "day" : "days"}
            </Button>
          ))}
        </div>
        <label className="order-5 hidden cursor-pointer items-center gap-2 text-xs text-slate-300 lg:flex" title="A simulated data manager approves drafts and accepts explanations (logged as sim:auto)">
          <input className="h-4 w-4 accent-teal-500" type="checkbox" checked={auto} onChange={(e) => setAuto(e.target.checked)} /> Auto-approve
        </label>
        {busy && <span role="status" aria-live="polite" className="text-xs text-slate-300">Advancing {selectedDays} days{job ? ` · ${job.done}/${job.total}` : "…"}</span>}
        <Badge className="order-2 ml-auto sm:order-none sm:ml-0" tone={apiOk ? "success" : "warning"}><span className={`h-1.5 w-1.5 rounded-full ${apiOk ? "bg-emerald-500" : "bg-amber-500"}`} />API {health.data ? (apiOk ? "online" : "no database") : "unreachable"}</Badge>
        <div className="order-1 ml-auto flex flex-wrap items-center gap-3 sm:order-none">
          <label className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/[.06] px-3 py-2 text-xs text-slate-400">Role
            <select className="max-w-44 bg-transparent font-medium text-white outline-none" value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {ROLES.map((r) => (<option key={r} value={r} className="text-black">{ROLE_LABEL[r] ?? r}</option>))}
            </select>
          </label>
          <Badge className={`hidden xl:inline-flex ${unblinded ? "bg-red-500/15 text-red-300" : "bg-emerald-500/15 text-emerald-300"}`}>
            {unblinded ? "UNBLINDED · AUDITED" : "BLINDED VIEW"}
          </Badge>
        </div>
      </div>
      {error && <div role="alert" className="border-t border-amber-400/20 bg-amber-400/10 px-5 py-2 text-sm text-amber-200">{error}</div>}
    </header>
  );
}
