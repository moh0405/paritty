"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRole } from "@/components/Providers";
import { api, type CheckRow, type Effectiveness, type GeneratedCheck } from "@/lib/api";

export default function ChecksPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [tab, setTab] = useState<"library" | "generated" | "effectiveness">("library");
  const [proposals, setProposals] = useState<GeneratedCheck[] | null>(null);
  const checks = useQuery({ queryKey: ["checks", role], queryFn: () => api<CheckRow[]>("/checks", role) });
  const eff = useQuery({ queryKey: ["check-eff", role], enabled: tab === "effectiveness", queryFn: () => api<Effectiveness[]>("/checks/effectiveness", role) });
  const gen = useMutation({ mutationFn: () => api<GeneratedCheck[]>("/checks/generate", role, { method: "POST", body: JSON.stringify({ use_llm: true }) }),
    onSuccess: (r) => { setProposals(r); qc.invalidateQueries({ queryKey: ["checks"] }); } });
  const decide = useMutation({ mutationFn: ({ id, ok }: { id: string; ok: boolean }) => api(`/checks/${id}/${ok ? "approve" : "reject"}`, role, { method: "POST", ...(!ok && { body: JSON.stringify({ reason: "not needed" }) }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["checks"] }) });
  const lib = (checks.data ?? []).filter((c) => c.source !== "generated");
  const generated = (checks.data ?? []).filter((c) => c.source === "generated");
  const isDM = role === "data_manager";
  return (
    <main className="space-y-4 p-6">
      <h1 className="text-xl font-semibold">Edit checks</h1>
      <div className="flex gap-3 text-sm">{(["library", "generated", "effectiveness"] as const).map((t) => (<button key={t} onClick={() => setTab(t)} className={`rounded px-3 py-1 ${tab === t ? "bg-gray-900 text-white" : "border"}`}>{t}</button>))}</div>
      {checks.error && <p className="text-red-700">{(checks.error as Error).message}</p>}
      {tab === "library" && (
        <table className="w-full text-sm"><thead className="text-left text-gray-500"><tr><th className="p-1">Check</th><th>What it looks for</th><th>Severity</th><th>Active</th><th>Failures</th><th>Open</th></tr></thead>
          <tbody>{lib.map((c) => (<tr key={c.id} className="border-t"><td className="p-1 font-mono">{c.id}</td><td>{c.description}</td><td>{c.severity}</td><td>{c.active ? "yes" : "no"}</td><td>{c.failures}</td><td>{c.open_failures}</td></tr>))}</tbody></table>
      )}
      {tab === "generated" && (
        <section className="space-y-3">
          <p className="text-sm text-gray-500">Checks proposed from the protocol text. Each shows the sentence that justifies it and how many existing rows it would flag. Nothing runs until a data manager approves it.</p>
          {isDM && <button className="rounded border px-3 py-1 text-sm hover:bg-gray-100 disabled:opacity-50" disabled={gen.isPending} onClick={() => gen.mutate()}>{gen.isPending ? "Reading the protocol…" : "Propose checks from the protocol"}</button>}
          {gen.error && <span className="text-red-700">{(gen.error as Error).message}</span>}
          {proposals && proposals.filter((p) => p.status === "rejected").map((p) => (<p key={p.id} className="text-sm text-amber-800">Not accepted: {p.description} — {p.reason}</p>))}
          {generated.length === 0 && <p className="text-sm text-gray-500">No generated checks yet.</p>}
          <ul className="space-y-2">{generated.map((c) => (
            <li key={c.id} className="rounded border p-3 text-sm">
              <div className="flex items-center gap-2"><span className="font-mono">{c.id}</span><b>{c.description}</b><span className={`rounded px-1.5 text-xs ${c.approval_status === "approved" ? "bg-green-100" : c.approval_status === "rejected" ? "bg-red-100" : "bg-amber-100"}`}>{c.approval_status.replace("_", " ")}</span></div>
              <blockquote className="mt-1 border-l-2 pl-2 text-gray-700">&ldquo;{c.rationale?.quote}&rdquo;<span className="ml-1 text-xs text-gray-500">protocol chunk {c.rationale?.chunk_id} · proposed by {c.rationale?.proposed_by}</span></blockquote>
              <div className="mt-1 text-gray-600">Would flag <b>{c.rationale?.dry_run_count ?? "?"}</b> existing rows{c.failures > 0 && ` · ${c.failures} flagged so far`}</div>
              {isDM && c.approval_status === "pending_approval" && (<div className="mt-2 flex gap-2"><button className="rounded border px-2 py-0.5 hover:bg-gray-100" onClick={() => decide.mutate({ id: c.id, ok: true })}>Approve</button><button className="rounded border px-2 py-0.5 hover:bg-gray-100" onClick={() => decide.mutate({ id: c.id, ok: false })}>Reject</button></div>)}
            </li>))}</ul>
        </section>
      )}
      {tab === "effectiveness" && (
        <table className="w-full text-sm"><thead className="text-left text-gray-500"><tr><th className="p-1">Check</th><th>Failures</th><th>Open</th><th>Confirmed by correction</th><th>Explained as correct</th><th></th></tr></thead>
          <tbody>{(eff.data ?? []).filter((e) => e.failures > 0).map((e) => (<tr key={e.check_id} className="border-t"><td className="p-1"><span className="font-mono">{e.check_id}</span> <span className="text-gray-500">{e.description}</span></td><td>{e.failures}</td><td>{e.open}</td><td>{e.confirmed}</td>
            <td>{e.dismissed}{e.dismissed_rate !== null && ` (${(e.dismissed_rate * 100).toFixed(0)}%)`}</td><td>{e.recommend_retire && <span className="rounded bg-amber-100 px-1.5 text-xs text-amber-900">consider retiring</span>}</td></tr>))}</tbody></table>
      )}
    </main>
  );
}
