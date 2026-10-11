"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, ReferenceArea, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { useRole } from "@/components/Providers";
import { api, type EdishPoint, type ReviewItem } from "@/lib/api";

const QUAD_COLOR: Record<string, string> = {
  "potential Hy's Law pattern": "#dc2626", "aminotransferase elevation": "#f97316", "bilirubin elevation": "#d97706", "within thresholds": "#93c5fd",
};
const PALETTE = ["#2563eb", "#16a34a", "#9333ea", "#0891b2", "#be123c", "#65a30d", "#c2410c", "#4338ca"];
const hash = (s: string) => [...s].reduce((a, c) => a + c.charCodeAt(0), 0);

export default function LiverPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [by, setBy] = useState<"flag" | "site" | "arm">("flag");
  const [reason, setReason] = useState("");
  const unblindedRole = role === "unblinded_statistician";
  const blinded = useQuery({ queryKey: ["edish", role], queryFn: () => api<{ points: EdishPoint[] }>("/medical/edish", role) });
  const arm = useQuery({ queryKey: ["edish-arm", role], enabled: unblindedRole && by === "arm",
    queryFn: () => api<{ points: EdishPoint[] }>("/unblinded/edish", role), retry: false });
  const unblind = useMutation({
    mutationFn: () => api("/unblind", role, { method: "POST", body: JSON.stringify({ reason }) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["edish-arm"] }),
  });
  const points = (by === "arm" && arm.data ? arm.data.points : blinded.data?.points) ?? [];
  const armNames = [...new Set(points.map((p) => p.arm ?? "unknown"))];
  const color = (p: EdishPoint) => by === "arm" ? PALETTE[armNames.indexOf(p.arm ?? "unknown") % PALETTE.length] : by === "site" ? PALETTE[hash(p.site_id) % PALETTE.length] : QUAD_COLOR[p.quadrant];
  const data = points.map((p) => ({ ...p, x: Math.max(0.1, p.peak_amino), y: Math.max(0.1, p.peak_bili) }));
  const review = useQuery({ queryKey: ["review-list", role], queryFn: () => api<ReviewItem[]>("/medical/review-list", role) });
  const hys = points.filter((p) => p.quadrant === "potential Hy's Law pattern").sort((a, b) => b.peak_amino - a.peak_amino);
  const creep = (review.data ?? []).find((i) => i.type === "site_creep");
  const cluster = (review.data ?? []).find((i) => i.type === "ae_cluster");
  return (
    <main className="space-y-5 p-6">
      <div>
        <h1>Liver safety (eDISH)</h1>
        <p className="mt-1 text-sm text-gray-500">Peak ALT/AST against peak bilirubin, both as multiples of the upper limit of normal. {by === "arm" ? "Coloured by treatment arm (unblinded, audited)." : "Points are not coloured by arm in the blinded view."}</p>
      </div>
      <div className="grid gap-5 xl:grid-cols-[1.9fr_1fr]">
        <section>
          <div className="flex flex-wrap items-center gap-3">
            <h2>Peak ALT/AST (x ULN) vs peak total bilirubin (x ULN)</h2>
            <label className="ml-auto text-xs text-gray-500">Colour by <select className="rounded-md border bg-white px-2 py-1 text-gray-800" value={by} onChange={(e) => setBy(e.target.value as typeof by)}>
              <option value="flag">flag</option><option value="site">site</option>{unblindedRole && <option value="arm">treatment arm (unblinded)</option>}</select></label>
          </div>
          {by === "arm" && (
            <div className="mt-2 flex items-center gap-2 text-sm">
              <input className="w-64 rounded border px-2 py-1" placeholder="reason for unblinding" value={reason} onChange={(e) => setReason(e.target.value)} />
              <button className="rounded border border-red-300 px-2 py-1 text-red-700 hover:bg-red-50" disabled={reason.trim().length < 5} onClick={() => unblind.mutate()}>Unblind (logged)</button>
              {(arm.error || unblind.error) && <span className="text-red-700">{((arm.error ?? unblind.error) as Error).message}</span>}
            </div>)}
          <div className="mt-2 h-[30rem]">
            <ResponsiveContainer>
              <ScatterChart margin={{ top: 10, right: 20, bottom: 24, left: 10 }}>
                <CartesianGrid stroke="#eef0f3" />
                <ReferenceArea x1={3} x2={30} y1={2} y2={15} fill="#fee2e2" fillOpacity={0.55} label={{ value: "Potential Hy's Law pattern: requires medical review", position: "insideTopRight", fill: "#dc2626", fontSize: 12, fontWeight: 600 }} />
                <XAxis type="number" dataKey="x" scale="log" domain={[0.5, 30]} ticks={[0.5, 1, 2, 3, 5, 10, 20]} allowDataOverflow tick={{ fontSize: 11 }} label={{ value: "Peak ALT (x ULN, log scale)", position: "bottom", fontSize: 12 }} />
                <YAxis type="number" dataKey="y" scale="log" domain={[0.5, 20]} ticks={[0.5, 1, 2, 3, 5, 10, 20]} allowDataOverflow tick={{ fontSize: 11 }} label={{ value: "Peak bili (x ULN)", angle: -90, position: "insideLeft", fontSize: 12 }} />
                <ReferenceLine x={3} stroke="#dc2626" /><ReferenceLine y={2} stroke="#dc2626" />
                <Tooltip content={({ payload }) => { const p = payload?.[0]?.payload as EdishPoint | undefined; return p ? (<div className="rounded border bg-white p-2 text-xs shadow"><div className="font-mono">{p.usubjid}</div><div>site {p.site_id}</div><div>ALT/AST {p.peak_amino.toFixed(1)}x · bilirubin {p.peak_bili.toFixed(1)}x</div><div>{p.quadrant}</div>{p.arm && <div>arm: {p.arm}</div>}</div>) : null; }} />
                <Scatter data={data} shape={(props: { cx?: number; cy?: number; payload?: EdishPoint }) => { const hot = props.payload?.quadrant === "potential Hy's Law pattern"; return <circle cx={props.cx} cy={props.cy} r={hot ? 7 : 4.5} fill={props.payload ? color(props.payload) : "#999"} fillOpacity={hot ? 0.95 : 0.75} />; }} />
              </ScatterChart>
            </ResponsiveContainer>
          </div>
          <p className="text-xs text-gray-500">{points.length} subjects with both a liver enzyme and bilirubin result. <Link className="text-teal-700 hover:underline" href="/medical">Back to the review list</Link></p>
        </section>

        <div className="space-y-5">
          <section>
            <h2>Potential pattern, needs review</h2>
            {hys.length === 0 && <p className="mt-3 text-sm text-gray-500">No subject is in the upper-right region right now.</p>}
            <ul className="mt-3 space-y-3">{hys.slice(0, 5).map((p) => (
              <li key={p.usubjid} className="rounded-xl border border-red-200 bg-red-50/60 p-3">
                <div className="flex items-center"><Link className="font-semibold hover:underline" href={`/medical/patients/${p.usubjid}`}>{p.usubjid}</Link><span className="ml-auto rounded-full bg-white px-2 py-0.5 text-xs font-semibold text-teal-700">lab rows</span></div>
                <div className="mt-1 text-sm text-gray-600">ALT {(p.peak_alt ?? p.peak_amino).toFixed(1)}x &nbsp; Bili {p.peak_bili.toFixed(1)}x</div>
              </li>))}</ul>
          </section>
          <section>
            <h2>Site ALT creep</h2>
            {creep ? (<><p className="mt-2 text-sm font-semibold">{creep.title}</p><p className="mt-1 text-xs text-gray-500">{creep.rule.threshold}</p>
              <Link className="mt-2 inline-block text-sm text-teal-700 hover:underline" href="/medical">Open review list</Link></>) : <p className="mt-2 text-sm text-gray-500">No site shows a rising ALT trend.</p>}
          </section>
          <section>
            <h2>Rare AE cluster</h2>
            {cluster ? (<><p className="mt-2 text-sm font-semibold">{cluster.title}</p><p className="mt-1 text-xs text-gray-500">{cluster.rule.threshold}</p>
              {cluster.usubjid && <Link className="mt-3 inline-block rounded-md bg-teal-600 px-3 py-2 text-sm font-semibold text-white hover:bg-teal-500" href={`/medical/patients/${cluster.usubjid}`}>Open patient profile</Link>}</>) : <p className="mt-2 text-sm text-gray-500">No clusters of a rare term.</p>}
          </section>
        </div>
      </div>
    </main>
  );
}
