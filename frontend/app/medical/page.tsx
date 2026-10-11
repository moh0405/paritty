"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { EvidencePanel } from "@/components/EvidencePanel";
import { TypeBadge } from "@/components/Badge";
import { useRole } from "@/components/Providers";
import { api, download, type Escalation, type ReviewItem } from "@/lib/api";

function EscalationLog() {
  const { role } = useRole();
  const qc = useQueryClient();
  const list = useQuery({ queryKey: ["escalations", role], queryFn: () => api<Escalation[]>("/medical/escalations", role) });
  const resolve = useMutation({
    mutationFn: ({ id, status }: { id: string; status: "acknowledged" | "resolved" }) =>
      api(`/medical/escalations/${id}`, role, { method: "PATCH", body: JSON.stringify({ status, resolution: status === "resolved" ? "Reviewed by the medical monitor" : undefined }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["escalations"] }),
  });
  return (
    <section className="space-y-1">
      <h2 className="font-medium">Escalation log</h2>
      {resolve.error && <p className="text-sm text-red-700">{(resolve.error as Error).message}</p>}
      <table className="w-full text-sm"><thead className="text-left text-gray-500"><tr><th>Raised</th><th>By</th><th>Subject</th><th>Reason</th><th>Status</th><th></th></tr></thead>
        <tbody>{(list.data ?? []).map((e) => (<tr key={e.id} className="border-t align-top"><td className="font-mono text-xs">{e.raised_at.slice(0, 10)}</td><td>{e.raised_by}</td><td className="font-mono">{e.usubjid ?? "—"}</td>
          <td>{e.reason}{e.resolution && <div className="text-xs text-gray-500">{e.resolution}</div>}</td><td>{e.status}</td>
          <td className="whitespace-nowrap">{e.status !== "resolved" && (<>{e.status === "open" && <button className="mr-1 rounded border px-2 hover:bg-gray-100" onClick={() => resolve.mutate({ id: e.id, status: "acknowledged" })}>Acknowledge</button>}<button className="rounded border px-2 hover:bg-gray-100" onClick={() => resolve.mutate({ id: e.id, status: "resolved" })}>Resolve</button></>)}</td></tr>))}
          {list.data?.length === 0 && <tr><td colSpan={6} className="p-2 text-gray-500">Nothing escalated yet.</td></tr>}</tbody></table>
    </section>
  );
}

export default function MedicalPage() {
  const { role } = useRole();
  const [evidence, setEvidence] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["review-list", role], queryFn: () => api<ReviewItem[]>("/medical/review-list", role) });
  return (
    <main className="space-y-3 p-6">
      <div className="flex items-center gap-3"><h1 className="text-xl font-semibold">Medical review list</h1>
        <button className="rounded border px-2 py-0.5 text-xs hover:bg-gray-100" onClick={() => download("/export/signal-pack.pdf", role, "signal-pack.pdf").catch((e) => alert((e as Error).message))}>Signal review pack (PDF)</button></div>
      <p className="text-sm text-gray-500">Ranked reasons to look: potential liver patterns first, then severe lab grades, site trends and clusters. Nothing here is a diagnosis; each item needs medical review. Treatment arm is never shown.</p>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      <table className="w-full text-sm">
        <thead className="text-left text-gray-500"><tr><th className="p-1">Score</th><th>Signal</th><th>Subject / site</th><th>Detail</th><th>Date</th><th>Evidence</th></tr></thead>
        <tbody>
          {(q.data ?? []).map((it, i) => (
            <tr key={i} className="border-t align-top">
              <td className="p-1 font-mono">{it.score}</td>
              <td><TypeBadge type={it.type} /></td>
              <td className="font-mono">{it.usubjid ? <Link className="text-teal-700 hover:underline" href={`/medical/patients/${it.usubjid}`}>{it.usubjid}</Link> : `site ${it.site_id}`}</td>
              <td>{it.title}<div className="text-xs text-gray-500">{it.rule.threshold}</div></td>
              <td className="font-mono">{it.day}</td>
              <td>{it.finding_id ? <button className="text-teal-700 hover:underline" onClick={() => setEvidence(it.finding_id)}>open</button> : "—"}
                {it.review_status && it.review_status !== "open" && <span className="ml-1 text-xs text-gray-500">{it.review_status}</span>}</td>
            </tr>
          ))}
          {q.data?.length === 0 && <tr><td colSpan={6} className="p-3 text-gray-500">No signals yet — advance the clock.</td></tr>}
        </tbody>
      </table>
      <EscalationLog />
      {evidence && <EvidencePanel findingId={evidence} onClose={() => setEvidence(null)} />}
    </main>
  );
}
