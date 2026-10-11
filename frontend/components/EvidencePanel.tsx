"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { api, type Citation, type Finding, type FindingClaim, type Source } from "@/lib/api";
import { useRole } from "./Providers";
import { VerificationBadge } from "./VerificationBadge";

function SourceView({ citation }: { citation: Citation }) {
  const { role } = useRole();
  const src = useQuery({
    queryKey: ["citation", citation.id, role],
    queryFn: () => api<Source>(`/citations/${citation.id}/source`, role),
  });
  if (src.isLoading) return <p className="text-xs text-gray-500">Loading source row…</p>;
  if (src.error) return <p className="text-xs text-red-700">{(src.error as Error).message}</p>;
  const s = src.data!;
  return (
    <div className="mt-2 rounded border bg-gray-50 p-2 text-xs">
      <div className="mb-1 font-mono text-gray-600">{s.table} #{s.pk}</div>
      {!s.matches && <p className="mb-1 text-red-700">The cited value no longer matches this cell.</p>}
      <table className="w-full">
        <tbody>
          {Object.entries(s.row).map(([k, v]) => (
            <tr key={k} className={k === s.column ? "bg-yellow-200 font-medium" : ""}>
              <td className="pr-2 align-top text-gray-500">{k}</td>
              <td className="break-all font-mono">{v === null ? "—" : typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ClaimView({ claim }: { claim: FindingClaim }) {
  const [open, setOpen] = useState<number | null>(null);
  const [showChecks, setShowChecks] = useState(false);
  return (
    <li className="rounded border p-2">
      <div className="flex items-start gap-2">
        <p className="flex-1">{claim.text}</p>
        <VerificationBadge status={claim.status} />
      </div>
      <div className="mt-1 flex flex-wrap gap-1">
        {claim.citations.map((c) => (
          <button key={c.id} onClick={() => setOpen(open === c.id ? null : c.id)}
            className={`rounded border px-1.5 py-0.5 font-mono text-xs hover:bg-gray-100 ${open === c.id ? "bg-yellow-100" : ""}`}>
            {c.table}#{c.pk} · {c.column}
          </button>
        ))}
        {claim.citations.length === 0 && <span className="text-xs text-red-700">no citations</span>}
      </div>
      {claim.citations.filter((c) => c.id === open).map((c) => <SourceView key={c.id} citation={c} />)}
      <button className="mt-1 text-xs text-gray-500 hover:underline" onClick={() => setShowChecks(!showChecks)}>
        {showChecks ? "Hide" : "Show"} verification checks ({claim.checks.filter((k) => k.passed).length}/{claim.checks.length} passed)
      </button>
      {showChecks && (
        <ul className="mt-1 space-y-0.5 text-xs">
          {claim.checks.map((k, i) => (
            <li key={i} className={k.passed ? "text-green-800" : "text-red-700"}>
              {k.passed ? "✓" : "✗"} {k.name}{k.detail && <span className="text-gray-600"> — {k.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function EvidencePanel({ findingId, onClose }: { findingId: string; onClose: () => void }) {
  const { role } = useRole();
  const qc = useQueryClient();
  const f = useQuery({ queryKey: ["finding", findingId, role], queryFn: () => api<Finding>(`/findings/${findingId}`, role) });
  const review = useMutation({
    mutationFn: (review_status: "confirmed" | "dismissed" | "open") =>
      api(`/findings/${findingId}`, role, { method: "PATCH", body: JSON.stringify({ review_status }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["finding", findingId] }),
  });
  const rule = f.data?.detail.rule;
  return (
    <aside className="fixed inset-y-0 right-0 z-20 w-full max-w-md overflow-y-auto border-l bg-white p-4 shadow-xl">
      <div className="flex items-start justify-between gap-2">
        <h2 className="font-semibold">Evidence</h2>
        <button onClick={onClose} className="rounded border px-2 text-sm hover:bg-gray-100" aria-label="Close evidence panel">✕</button>
      </div>
      {f.isLoading && <p className="mt-2 text-gray-500">Loading…</p>}
      {f.error && <p className="mt-2 text-red-700">{(f.error as Error).message}</p>}
      {f.data && (
        <div className="mt-2 space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <VerificationBadge status={f.data.verification_status} />
            <span className="text-gray-600">{f.data.title}</span>
            {f.data.detail.source && <span className="rounded bg-gray-100 px-1.5 text-xs">text: {f.data.detail.source}{f.data.detail.model ? ` (${f.data.detail.model})` : ""}</span>}
          </div>
          {rule && (
            <div className="rounded border bg-gray-50 p-2 text-xs">
              <div className="font-medium">Rule {rule.rule}: {rule.description}</div>
              <div>Observed: <span className="font-mono">{rule.observed ?? "n/a"}</span> · Expected: <span className="font-mono">{rule.expected ?? "n/a"}</span></div>
            </div>
          )}
          <ul className="space-y-2">{f.data.claims.map((c) => <ClaimView key={c.idx} claim={c} />)}</ul>
          <div className="flex items-center gap-2 border-t pt-2 text-xs">
            <span className="text-gray-500">Review: {f.data.review_status}</span>
            <button className="rounded border px-2 py-0.5 hover:bg-gray-100" onClick={() => review.mutate("confirmed")}>Reason to look</button>
            <button className="rounded border px-2 py-0.5 hover:bg-gray-100" onClick={() => review.mutate("dismissed")}>Dismiss</button>
            {review.error && <span className="text-red-700">{(review.error as Error).message}</span>}
          </div>
        </div>
      )}
    </aside>
  );
}
