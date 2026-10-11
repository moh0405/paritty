"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { RagDot } from "@/components/Rag";
import { useRole } from "@/components/Providers";
import { api, type SitesList } from "@/lib/api";

export default function SitesPage() {
  const { role } = useRole();
  const q = useQuery({ queryKey: ["sites", role], queryFn: () => api<SitesList>("/sites", role) });
  const defs = q.data?.kri_defs ?? {};
  const keys = Object.keys(defs);
  return (
    <main className="space-y-3 p-6">
      <h1 className="text-xl font-semibold">Site risk</h1>
      <p className="text-sm text-gray-500">Sites ranked by how unusual their data look compared with the rest of the study{q.data?.as_of ? ` (as of ${q.data.as_of})` : ""}. A high score is a reason to look, not a conclusion. The model score comes from a model trained on simulated sites. <Link className="text-blue-700 hover:underline" href="/sites/visit-plan">Monitoring plan</Link></p>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      <div className="overflow-x-auto">
        <table className="text-sm">
          <thead className="text-left text-gray-500">
            <tr><th className="p-1">Site</th><th className="pr-3">Rule score</th><th className="pr-3">Model score</th><th className="pr-3">Subjects</th>
              {keys.map((k) => (<th key={k} className="px-1 text-center font-normal" title={defs[k].label}>{k.split("_").map((w) => w[0].toUpperCase()).join("")}</th>))}</tr>
          </thead>
          <tbody>
            {(q.data?.sites ?? []).map((s) => (
              <tr key={s.site_id} className="border-t">
                <td className="p-1"><Link className="font-mono text-blue-700 hover:underline" href={`/sites/${s.site_id}`}>{s.site_id}</Link> <span className="text-gray-500">{s.name}</span></td>
                <td className="pr-3"><div className="flex items-center gap-2"><div className="h-2 w-24 rounded bg-gray-100"><div className="h-2 rounded bg-amber-500" style={{ width: `${s.rule_score}%` }} /></div><span className="font-mono">{s.rule_score.toFixed(0)}</span></div></td>
                <td className="pr-3 font-mono">{s.model_score === null ? "—" : s.model_score.toFixed(0)}</td>
                <td className="pr-3">{s.subjects}</td>
                {keys.map((k) => (<td key={k} className="px-1 text-center"><RagDot rag={s.kris[k]?.rag ?? "na"} title={`${defs[k].label}: ${s.kris[k]?.value?.toFixed(2) ?? "n/a"}`} /></td>))}
              </tr>
            ))}
            {q.data?.sites.length === 0 && <tr><td colSpan={4 + keys.length} className="p-3 text-gray-500">No site data yet — advance the clock.</td></tr>}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-500">Columns: {keys.map((k) => `${k.split("_").map((w) => w[0].toUpperCase()).join("")} = ${defs[k].label}`).join(" · ")}</p>
    </main>
  );
}
