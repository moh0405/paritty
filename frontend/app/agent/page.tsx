"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRole } from "@/components/Providers";
import { api, type AgentAction } from "@/lib/api";

export default function AgentPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const actions = useQuery({ queryKey: ["agent-actions", role], queryFn: () => api<AgentAction[]>("/agent/actions", role) });
  const status = useQuery({ queryKey: ["agent-status", role], queryFn: () => api<{ enabled: boolean; approved_speedups: Record<string, number> }>("/agent/status", role) });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["agent-actions"] }); qc.invalidateQueries({ queryKey: ["agent-status"] }); };
  const plan = useMutation({ mutationFn: () => api<{ proposed: number }>("/agent/plan", role, { method: "POST" }), onSuccess: refresh });
  const toggle = useMutation({ mutationFn: (enabled: boolean) => api("/agent/enable", role, { method: "POST", body: JSON.stringify({ enabled }) }), onSuccess: refresh });
  const decide = useMutation({ mutationFn: ({ id, action }: { id: string; action: "approve" | "reject" }) => api(`/drafts/${id}/${action}`, role, { method: "POST", body: JSON.stringify({}) }), onSuccess: refresh });
  const err = (plan.error ?? toggle.error ?? decide.error) as Error | null;
  const list = actions.data ?? [];
  return (
    <main className="space-y-4 p-6">
      <div><h1 className="text-xl font-semibold">Data-manager agent</h1>
        <p className="text-sm text-gray-500">Suggests up to five actions that should bring the lock date forward, with a simulated estimate of the effect. Nothing happens until you approve it; an approved action speeds up that site&apos;s future answers in the simulation.</p></div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <button className="rounded border px-3 py-1 hover:bg-gray-100 disabled:opacity-50" disabled={plan.isPending} onClick={() => plan.mutate()}>{plan.isPending ? "Thinking…" : "Propose actions now"}</button>
        <label className="flex items-center gap-1"><input type="checkbox" checked={status.data?.enabled ?? false} onChange={(e) => toggle.mutate(e.target.checked)} /> run weekly in the simulation</label>
        {plan.data && <span className="text-gray-600">{plan.data.proposed === 0 ? "No action is worth proposing right now." : `${plan.data.proposed} proposed.`}</span>}
        {err && <span className="text-red-700">{err.message}</span>}
      </div>
      {status.data && Object.keys(status.data.approved_speedups).length > 0 && <p className="text-sm text-gray-600">Approved speed-ups: {Object.entries(status.data.approved_speedups).map(([s, f]) => `site ${s} answers in ${(f * 100).toFixed(0)}% of its usual time`).join("; ")}.</p>}
      <table className="w-full text-sm"><thead className="text-left text-gray-500"><tr><th>Site</th><th>Action</th><th>Why</th><th>Expected effect</th><th>State</th><th></th></tr></thead>
        <tbody>{list.map((a) => (
          <tr key={a.id} className="border-t align-top"><td className="py-1 font-mono">{a.site_id}</td><td>{a.body.label}</td>
            <td className="max-w-md">{a.body.text}<div className="text-xs text-gray-400">{a.body.source === "gemini" ? "AI wording, numbers checked" : "template wording"}</div></td>
            <td className="font-mono">{Math.round(a.body.est_delta_p50_days)} days earlier</td><td>{a.state}{a.approved_by ? ` by ${a.approved_by}` : ""}</td>
            <td className="whitespace-nowrap">{a.state === "draft" && (<><button className="mr-1 rounded border px-2 hover:bg-gray-100" onClick={() => decide.mutate({ id: a.id, action: "approve" })}>Approve</button>
              <button className="rounded border px-2 hover:bg-gray-100" onClick={() => decide.mutate({ id: a.id, action: "reject" })}>Reject</button></>)}</td></tr>))}
          {list.length === 0 && <tr><td colSpan={6} className="p-3 text-gray-500">No proposals yet.</td></tr>}</tbody></table>
    </main>
  );
}
