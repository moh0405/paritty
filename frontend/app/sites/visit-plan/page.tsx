"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { RagDot } from "@/components/Rag";
import { useRole } from "@/components/Providers";
import { api, type SiteDraft, type VisitPlan } from "@/lib/api";

const ACTION_LABELS: Record<string, string> = { visit: "On-site visit", call: "Call", remote: "Remote review" };
const ACTION_COLORS: Record<string, string> = { visit: "bg-red-100 text-red-800", call: "bg-amber-100 text-amber-900", remote: "bg-gray-100 text-gray-700" };
const MONITOR_ROLES = ["central_monitor", "data_manager"];

export default function VisitPlanPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const canAct = MONITOR_ROLES.includes(role);
  const plan = useQuery({ queryKey: ["visit-plan", role], queryFn: () => api<VisitPlan>("/sites/visit-plan", role) });
  const drafts = useQuery({ queryKey: ["site-drafts", role], queryFn: async () =>
    [...(await api<SiteDraft[]>("/drafts?kind=agenda&state=draft", role)), ...(await api<SiteDraft[]>("/drafts?kind=letter&state=draft", role))] });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["site-drafts"] }); qc.invalidateQueries({ queryKey: ["visit-plan"] }); };
  const draft = useMutation({ mutationFn: ({ site, kind }: { site: string; kind: "agenda" | "letter" }) => api<SiteDraft>(`/sites/${site}/${kind}`, role, { method: "POST" }), onSuccess: refresh });
  const decide = useMutation({ mutationFn: ({ id, ok }: { id: string; ok: boolean }) =>
    api(`/drafts/${id}/${ok ? "approve" : "reject"}`, role, { method: "POST", ...(!ok && { body: JSON.stringify({ reason: "not needed" }) }) }), onSuccess: refresh });
  const error = plan.error ?? drafts.error ?? draft.error ?? decide.error;
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>Monitoring plan{plan.data ? ` for ${plan.data.month}` : ""}</h1>
        <p className="mt-1 text-sm text-gray-500">Sites ranked by risk score times enrolled subjects{plan.data?.as_of ? ` (data as of ${plan.data.as_of})` : ""}. Two or more red indicators propose a visit, one red or two amber a call, and open issues at a quiet site a remote review. Each row is a reason to look, not a conclusion. <Link className="text-teal-700 hover:underline" href="/sites">Back to site risk</Link></p>
      </div>
      {error && <p className="text-red-700">{(error as Error).message}</p>}
      <section className="overflow-x-auto !p-0">
        <table className="w-full min-w-[900px] text-sm">
          <thead><tr className="text-left"><th className="px-5 py-3">Site</th><th>Proposed</th><th>Priority</th><th>Subjects</th><th>Red / amber</th><th>Open issues</th><th>Last monitoring visit</th>{canAct && <th>Draft for approval</th>}</tr></thead>
          <tbody>
            {(plan.data?.sites ?? []).map((s) => (
              <tr key={s.site_id} className="border-t align-top">
                <td className="px-5 py-3"><span className="mr-1"><RagDot rag={s.level} /></span><Link className="font-semibold hover:underline" href={`/sites/${s.site_id}`}>Site {s.site_id}</Link> <span className="text-gray-500">{s.name}</span>
                  {s.reasons.length > 0 && <details className="text-xs text-gray-600"><summary className="cursor-pointer">{s.reasons.length} reason{s.reasons.length === 1 ? "" : "s"} to look</summary><ul className="list-disc pl-4">{s.reasons.map((r, i) => (<li key={i}>{r}</li>))}</ul></details>}</td>
                <td><span className={`rounded px-1.5 py-0.5 text-xs font-medium ${ACTION_COLORS[s.action]}`}>{ACTION_LABELS[s.action]}</span></td>
                <td className="font-mono">{s.priority.toFixed(1)}</td><td>{s.subjects}</td><td>{s.reds} / {s.ambers}</td><td>{s.open_issues}</td>
                <td>{s.last_monitoring_visit ? `${s.last_monitoring_visit} (${s.days_since_visit} days ago)` : "none on record"}</td>
                {canAct && <td className="space-x-2 whitespace-nowrap pr-5">{(["agenda", "letter"] as const).map((kind) => (
                  <button key={kind} className="rounded border px-2 py-0.5 text-xs hover:bg-gray-100 disabled:opacity-50" disabled={draft.isPending} onClick={() => draft.mutate({ site: s.site_id, kind })}>Draft {kind}</button>))}</td>}
              </tr>
            ))}
            {plan.data?.sites.length === 0 && <tr><td colSpan={8} className="p-5 text-gray-500">{plan.data.as_of ? "No site needs contact this month." : "No site data yet — advance the clock."}</td></tr>}
          </tbody>
        </table>
      </section>
      <section className="space-y-2">
        <h2>Drafts awaiting approval ({drafts.data?.length ?? 0})</h2>
        <p className="text-sm text-gray-500">Nothing is sent to a site until a central monitor or data manager approves it. Approving an agenda opens one tracked issue per point; approving a letter opens a follow-up issue.</p>
        {drafts.data?.length === 0 && <p className="text-sm text-gray-500">No drafts waiting.</p>}
        <ul className="space-y-2">{(drafts.data ?? []).map((d) => (
          <li key={d.id} className="rounded border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2"><b className="capitalize">{d.kind}</b><Link className="font-mono text-teal-700 hover:underline" href={`/sites/${d.site_id}`}>site {d.site_id}</Link>
              <span className="rounded bg-gray-100 px-1.5 text-xs">{d.body.source === "gemini" ? "drafted by Gemini, verified" : "template, verified facts"}</span>
              {d.body.items && <span className="text-xs text-gray-500">{d.body.items.length} point{d.body.items.length === 1 ? "" : "s"}</span>}</div>
            <pre className="mt-2 whitespace-pre-wrap rounded bg-gray-50 p-2 font-sans text-gray-800">{d.body.text}</pre>
            {canAct && <div className="mt-2 space-x-2"><button className="rounded bg-gray-900 px-3 py-1 text-xs text-white disabled:opacity-50" disabled={decide.isPending} onClick={() => decide.mutate({ id: d.id, ok: true })}>Approve</button>
              <button className="rounded border px-3 py-1 text-xs hover:bg-gray-100 disabled:opacity-50" disabled={decide.isPending} onClick={() => decide.mutate({ id: d.id, ok: false })}>Reject</button></div>}
          </li>))}</ul>
      </section>
    </main>
  );
}
