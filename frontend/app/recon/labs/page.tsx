"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ClassBadge } from "@/components/ClassBadge";
import { useRole } from "@/components/Providers";
import { api, type LabRecon } from "@/lib/api";

const LABEL: Record<string, string> = { chk_24: "value differs", chk_25: "one side only", chk_26: "unit differs", lab_stale_feed: "feed late" };

export default function LabReconPage() {
  const { role } = useRole();
  const [state, setState] = useState("open");
  const q = useQuery({ queryKey: ["lab-recon", role, state], queryFn: () => api<LabRecon>(`/recon/labs?state=${state}`, role) });
  const d = q.data;
  return (
    <main className="space-y-4 p-6">
      <h1 className="text-xl font-semibold">Central lab reconciliation</h1>
      <p className="text-sm text-gray-500">Central lab results are matched to the EDC by subject, test and collection date (±1 day). Bilirubin is converted from µmol/L before values are compared (1% tolerance).</p>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      {d && (
        <>
          <div className={`rounded border p-3 text-sm ${d.feed.stale ? "border-amber-400 bg-amber-50" : ""}`}>
            Latest central lab file: <b>{d.feed.last_file ?? "none"}</b>{d.feed.days_since !== null && ` (${d.feed.days_since} days ago)`}.{" "}
            {d.feed.stale ? "The feed is late while samples are still being collected, so results may be missing for now." : "The feed is current."}
          </div>
          <div className="flex gap-4 text-sm"><span>Value differences: <b>{d.open_by_type.value}</b></span><span>Present on one side only: <b>{d.open_by_type.one_sided}</b></span><span>Unit differences: <b>{d.open_by_type.unit}</b></span></div>
          <label className="text-sm">Show <select className="rounded border px-2 py-1" value={state} onChange={(e) => setState(e.target.value)}><option value="open">open</option><option value="resolved">resolved</option><option value="all">all</option></select></label>
          <table className="w-full text-sm">
            <thead className="text-left text-gray-500"><tr><th className="p-1">Type</th><th>Subject</th><th>Site</th><th>What differs</th><th>Detected</th><th>Query</th></tr></thead>
            <tbody>{d.items.map((i) => (
              <tr key={i.id} className="border-t align-top"><td className="p-1"><ClassBadge cls={i.check_id === "chk_26" ? "acceptable" : "actionable"} /> {LABEL[i.check_id]}</td>
                <td className="font-mono">{i.usubjid ?? "—"}</td><td className="font-mono">{i.site_id ?? "—"}</td><td>{i.observed}<div className="text-xs text-gray-500">{i.expected}</div></td>
                <td className="font-mono">{i.detected_on}{i.resolved_on && ` → ${i.resolved_on}`}</td><td>{i.query_state ?? "—"}</td></tr>))}
              {d.items.length === 0 && <tr><td colSpan={6} className="p-3 text-gray-500">Nothing to show.</td></tr>}</tbody>
          </table>
        </>
      )}
    </main>
  );
}
