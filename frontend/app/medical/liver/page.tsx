"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { CartesianGrid, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { useRole } from "@/components/Providers";
import { api, type EdishPoint } from "@/lib/api";

const QUAD_COLOR: Record<string, string> = {
  "potential Hy's Law pattern": "#dc2626", "aminotransferase elevation": "#f97316", "bilirubin elevation": "#d97706", "within thresholds": "#6b7280",
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
  return (
    <main className="space-y-3 p-6">
      <h1 className="text-xl font-semibold">Liver safety (eDISH)</h1>
      <p className="text-sm text-gray-500">Peak ALT/AST against peak bilirubin, both as multiples of the upper limit of normal. Points in the upper right need medical review; they are reasons to look, not diagnoses.</p>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>Colour by <select className="rounded border px-2 py-1" value={by} onChange={(e) => setBy(e.target.value as typeof by)}>
          <option value="flag">flag</option><option value="site">site</option>{unblindedRole && <option value="arm">treatment arm (unblinded)</option>}</select></label>
        {by === "arm" && (
          <span className="flex items-center gap-2">
            <input className="w-64 rounded border px-2 py-1" placeholder="reason for unblinding" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="rounded border border-red-300 px-2 py-1 text-red-700 hover:bg-red-50" disabled={reason.trim().length < 5} onClick={() => unblind.mutate()}>Unblind (logged)</button>
            {(arm.error || unblind.error) && <span className="text-red-700">{((arm.error ?? unblind.error) as Error).message}</span>}
          </span>
        )}
      </div>
      <div className="h-[28rem] max-w-4xl rounded border bg-white p-2">
        <ResponsiveContainer>
          <ScatterChart margin={{ top: 10, right: 20, bottom: 20, left: 10 }}>
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" dataKey="x" scale="log" domain={[0.1, 30]} allowDataOverflow name="Peak ALT/AST (x ULN)" label={{ value: "Peak ALT/AST (x ULN)", position: "bottom", fontSize: 12 }} />
            <YAxis type="number" dataKey="y" scale="log" domain={[0.1, 15]} allowDataOverflow name="Peak bilirubin (x ULN)" label={{ value: "Peak bilirubin (x ULN)", angle: -90, position: "insideLeft", fontSize: 12 }} />
            <ReferenceLine x={3} stroke="#dc2626" strokeDasharray="4 2" /><ReferenceLine y={2} stroke="#dc2626" strokeDasharray="4 2" />
            <Tooltip content={({ payload }) => { const p = payload?.[0]?.payload as EdishPoint | undefined; return p ? (<div className="rounded border bg-white p-2 text-xs"><div className="font-mono">{p.usubjid}</div><div>site {p.site_id}</div><div>ALT/AST {p.peak_amino.toFixed(1)}x · bilirubin {p.peak_bili.toFixed(1)}x</div><div>{p.quadrant}</div>{p.arm && <div>arm: {p.arm}</div>}</div>) : null; }} />
            <Scatter data={data} shape={(props: { cx?: number; cy?: number; payload?: EdishPoint }) => <circle cx={props.cx} cy={props.cy} r={5} fill={props.payload ? color(props.payload) : "#999"} fillOpacity={0.8} />} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-gray-500">{points.length} subjects with both a liver enzyme and bilirubin result. <Link className="text-blue-700 hover:underline" href="/medical">Back to the review list</Link></p>
    </main>
  );
}
