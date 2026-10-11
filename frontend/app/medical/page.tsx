"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { EvidencePanel } from "@/components/EvidencePanel";
import { TypeBadge } from "@/components/Badge";
import { useRole } from "@/components/Providers";
import { api, type ReviewItem } from "@/lib/api";

export default function MedicalPage() {
  const { role } = useRole();
  const [evidence, setEvidence] = useState<string | null>(null);
  const q = useQuery({ queryKey: ["review-list", role], queryFn: () => api<ReviewItem[]>("/medical/review-list", role) });
  return (
    <main className="space-y-3 p-6">
      <h1 className="text-xl font-semibold">Medical review list</h1>
      <p className="text-sm text-gray-500">Ranked reasons to look: potential liver patterns first, then severe lab grades, site trends and clusters. Nothing here is a diagnosis; each item needs medical review. Treatment arm is never shown.</p>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      <table className="w-full text-sm">
        <thead className="text-left text-gray-500"><tr><th className="p-1">Score</th><th>Signal</th><th>Subject / site</th><th>Detail</th><th>Date</th><th>Evidence</th></tr></thead>
        <tbody>
          {(q.data ?? []).map((it, i) => (
            <tr key={i} className="border-t align-top">
              <td className="p-1 font-mono">{it.score}</td>
              <td><TypeBadge type={it.type} /></td>
              <td className="font-mono">{it.usubjid ? <Link className="text-blue-700 hover:underline" href={`/medical/patients/${it.usubjid}`}>{it.usubjid}</Link> : `site ${it.site_id}`}</td>
              <td>{it.title}<div className="text-xs text-gray-500">{it.rule.threshold}</div></td>
              <td className="font-mono">{it.day}</td>
              <td>{it.finding_id ? <button className="text-blue-700 hover:underline" onClick={() => setEvidence(it.finding_id)}>open</button> : "—"}
                {it.review_status && it.review_status !== "open" && <span className="ml-1 text-xs text-gray-500">{it.review_status}</span>}</td>
            </tr>
          ))}
          {q.data?.length === 0 && <tr><td colSpan={6} className="p-3 text-gray-500">No signals yet — advance the clock.</td></tr>}
        </tbody>
      </table>
      {evidence && <EvidencePanel findingId={evidence} onClose={() => setEvidence(null)} />}
    </main>
  );
}
