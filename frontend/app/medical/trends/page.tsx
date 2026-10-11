"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { useRole } from "@/components/Providers";
import { api, type Clusters, type Trend } from "@/lib/api";

const TESTS = ["ALT", "AST", "ALP", "BILI", "CREAT", "HGB", "PLAT"];
const COLORS = ["#2563eb", "#16a34a", "#9333ea", "#0891b2", "#be123c", "#65a30d", "#c2410c", "#4338ca", "#0d9488", "#a21caf"];

export default function TrendsPage() {
  const { role } = useRole();
  const [test, setTest] = useState("ALT");
  const [by, setBy] = useState<"site" | "visit">("site");
  const [pick, setPick] = useState("");
  const trend = useQuery({ queryKey: ["trend", test, by, role], queryFn: () => api<Trend>(`/medical/trends?test=${test}&by=${by}`, role) });
  const clusters = useQuery({ queryKey: ["clusters", role], queryFn: () => api<Clusters>("/medical/clusters", role) });
  const days = [...new Set((trend.data?.series ?? []).flatMap((s) => s.points.map((p) => p.planned_day)))].sort((a, b) => a - b);
  const keys = (trend.data?.series ?? []).map((s) => s.key);
  const shown = keys.filter((k) => k === "study" || !pick || k === pick);
  const data = days.map((d) => ({ day: d, ...Object.fromEntries((trend.data?.series ?? []).map((s) => [s.key, s.points.find((p) => p.planned_day === d)?.mean])) }));
  return (
    <main className="space-y-5 p-6">
      <h1 className="text-xl font-semibold">Lab trends and clusters</h1>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label>Test <select className="rounded border px-2 py-1" value={test} onChange={(e) => setTest(e.target.value)}>{TESTS.map((t) => (<option key={t}>{t}</option>))}</select></label>
        <label>Group by <select className="rounded border px-2 py-1" value={by} onChange={(e) => setBy(e.target.value as "site" | "visit")}><option value="site">site</option><option value="visit">visit (whole study)</option></select></label>
        {by === "site" && <label>Highlight site <select className="rounded border px-2 py-1" value={pick} onChange={(e) => setPick(e.target.value)}><option value="">all sites</option>{keys.filter((k) => k !== "study").map((k) => (<option key={k}>{k}</option>))}</select></label>}
      </div>
      {trend.error && <p className="text-red-700">{(trend.error as Error).message}</p>}
      <div className="h-80 max-w-5xl rounded border bg-white p-2">
        <ResponsiveContainer>
          <LineChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" label={{ value: "planned study day", position: "bottom", fontSize: 12 }} /><YAxis width={40} label={{ value: `${test} (x ULN)`, angle: -90, position: "insideLeft", fontSize: 12 }} />
            <Tooltip /><Legend />
            {shown.map((k, i) => (<Line key={k} dataKey={k} connectNulls dot={false} isAnimationActive={false} stroke={k === "study" ? "#111827" : COLORS[i % COLORS.length]} strokeWidth={k === "study" ? 3 : 1.5} strokeDasharray={k === "study" ? undefined : pick ? undefined : "4 2"} />))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-xs text-gray-500">Mean multiple of the upper limit of normal by planned visit. A site line drifting away from the black study line is a reason to look, not a conclusion.</p>
      <section className="grid gap-4 md:grid-cols-2">
        <div className="rounded border p-3"><h2 className="mb-1 font-medium">Rare adverse event clusters</h2>
          {clusters.data?.ae_clusters.length ? (<ul className="space-y-1 text-sm">{clusters.data.ae_clusters.map((c) => (<li key={c.site_id + c.term}>Site <b>{c.site_id}</b>: {c.count} subjects with {c.term.toLowerCase()} (about {c.expected.toFixed(2)} expected, p = {c.p_value.toExponential(1)})</li>))}</ul>) : <p className="text-sm text-gray-500">None at the moment.</p>}</div>
        <div className="rounded border p-3"><h2 className="mb-1 font-medium">Sites with rising ALT</h2>
          {clusters.data?.alt_creep.length ? (<ul className="space-y-1 text-sm">{clusters.data.alt_creep.map((c) => (<li key={c.site_id}>Site <b>{c.site_id}</b>: median trend {(c.median_slope * 14).toFixed(2)}x ULN per 2 weeks across {c.n_subjects} subjects (robust z {c.z.toFixed(1)})</li>))}</ul>) : <p className="text-sm text-gray-500">None at the moment.</p>}</div>
      </section>
    </main>
  );
}
