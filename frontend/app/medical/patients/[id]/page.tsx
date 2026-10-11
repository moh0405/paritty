"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useParams } from "next/navigation";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { TypeBadge } from "@/components/Badge";
import { useRole } from "@/components/Providers";
import { EvidencePanel } from "@/components/EvidencePanel";
import { VerificationBadge } from "@/components/VerificationBadge";
import { api, type Draft, type Profile } from "@/lib/api";

const day = (d: string) => Date.parse(d) / 86400000;
const GRADE_FILL = ["#9ca3af", "#fde68a", "#fbbf24", "#f97316", "#dc2626", "#7f1d1d"];

function Swimlanes({ p }: { p: Profile }) {
  const all = [p.subject.consent_at, ...p.visits.map((v) => v.actual_date), ...p.adverse_events.map((a) => a.onset_at), ...p.dosing.map((d) => d.start_at)].filter(Boolean).map(day);
  const lo = Math.min(...all), hi = Math.max(...all, ...p.adverse_events.map((a) => (a.end_at ? day(a.end_at) : 0)), ...p.dosing.map((d) => (d.end_at ? day(d.end_at) : 0)));
  const W = 900, pad = 90, x = (d: string | null) => pad + ((day(d ?? p.subject.consent_at) - lo) / Math.max(1, hi - lo)) * (W - pad - 10);
  const lanes = ["Dosing", "Visits", "Adverse events", "Con. meds"];
  const aeRows = p.adverse_events.slice(0, 12);
  const H = 40 + lanes.length * 28 + aeRows.length * 10;
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full rounded border bg-white" role="img" aria-label="Subject timeline">
      {lanes.map((l, i) => (<text key={l} x={4} y={30 + i * 28} fontSize={11} fill="#6b7280">{l}</text>))}
      {p.dosing.map((d) => (<rect key={d.id} x={x(d.start_at)} y={20} width={Math.max(2, x(d.end_at ?? d.start_at) - x(d.start_at))} height={12} fill="#60a5fa" />))}
      {p.visits.map((v) => (<line key={v.id} x1={x(v.actual_date)} x2={x(v.actual_date)} y1={48} y2={62} stroke="#374151"><title>{v.visit} {v.actual_date}</title></line>))}
      {aeRows.map((a, i) => (
        <g key={a.id}>
          <rect x={x(a.onset_at)} y={76 + i * 10} width={Math.max(4, x(a.end_at ?? a.onset_at) - x(a.onset_at))} height={7} fill={GRADE_FILL[a.ctcae_grade ?? 0]} stroke={a.serious ? "#000" : "none"}>
            <title>{a.term_coded} (grade {a.ctcae_grade ?? "?"}{a.serious ? ", serious" : ""})</title>
          </rect>
        </g>
      ))}
      {p.conmeds.slice(0, 40).map((c) => (<rect key={c.id} x={x(c.start_at)} y={H - 18} width={Math.max(2, x(c.end_at ?? c.start_at) - x(c.start_at))} height={4} fill="#a78bfa" opacity={0.6} />))}
    </svg>
  );
}

function LabChart({ test, rows, linkDays }: { test: string; rows: Profile["labs"][string]; linkDays: string[] }) {
  const data = rows.filter((r) => r.x_uln !== null).map((r) => ({ day: r.day, x: r.x_uln, grade: r.ctcae_grade }));
  return (
    <div className="rounded border p-2">
      <div className="text-sm font-medium">{test} <span className="text-xs text-gray-500">(multiples of ULN)</span></div>
      <div className="h-32">
        <ResponsiveContainer>
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="day" tick={{ fontSize: 10 }} minTickGap={30} /><YAxis width={28} tick={{ fontSize: 10 }} />
            <ReferenceLine y={1} stroke="#9ca3af" /><ReferenceLine y={test === "BILI" ? 2 : 3} stroke="#dc2626" strokeDasharray="4 2" />
            {linkDays.map((d) => (<ReferenceLine key={d} x={d} stroke="#7c3aed" strokeDasharray="2 2" />))}
            <Tooltip /><Line dataKey="x" stroke="#2563eb" dot={{ r: 2 }} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function NotePanel({ usubjid }: { usubjid: string }) {
  const { role } = useRole();
  const qc = useQueryClient();
  const [text, setText] = useState<string | null>(null);
  const [why, setWhy] = useState("");
  const [evidence, setEvidence] = useState<string | null>(null);
  const notes = useQuery({ queryKey: ["notes", usubjid, role], queryFn: () => api<Draft[]>(`/drafts?kind=note&subject=${usubjid}`, role) });
  const note = notes.data?.find((n) => n.state !== "rejected");
  const refresh = () => qc.invalidateQueries({ queryKey: ["notes"] });
  const draft = useMutation({ mutationFn: () => api(`/medical/patients/${usubjid}/notes`, role, { method: "POST" }), onSuccess: refresh });
  const save = useMutation({ mutationFn: () => api(`/drafts/${note!.id}`, role, { method: "PATCH", body: JSON.stringify({ text }) }), onSuccess: () => { setText(null); refresh(); } });
  const sign = useMutation({ mutationFn: () => api(`/drafts/${note!.id}/sign`, role, { method: "POST" }), onSuccess: refresh });
  const escalate = useMutation({ mutationFn: () => api("/medical/escalations", role, { method: "POST", body: JSON.stringify({ usubjid, reason: why }) }), onSuccess: () => setWhy("") });
  const err = (draft.error ?? save.error ?? sign.error ?? escalate.error) as Error | null;
  return (
    <section className="rounded border p-3">
      <h2 className="mb-1 font-medium">Review note</h2>
      {!note ? (
        <button className="rounded border px-3 py-1 text-sm hover:bg-gray-100" onClick={() => draft.mutate()} disabled={draft.isPending}>{draft.isPending ? "Drafting…" : "Draft a review note from the flagged findings"}</button>
      ) : (
        <div className="space-y-2 text-sm">
          <div className="flex items-center gap-2"><span className="rounded bg-gray-100 px-2 py-0.5">{note.state}</span><VerificationBadge status={note.body.verification_status} />
            {note.body.finding_id && <button className="text-blue-700 hover:underline" onClick={() => setEvidence(note.body.finding_id!)}>evidence</button>}
            {note.approved_by && <span className="text-gray-500">by {note.approved_by}</span>}</div>
          {note.state === "draft" ? (
            <>
              <textarea className="h-28 w-full rounded border p-2" value={text ?? note.body.text ?? ""} onChange={(e) => setText(e.target.value)} />
              <div className="flex gap-2">
                {text !== null && <button className="rounded border px-3 py-1 hover:bg-gray-100" onClick={() => save.mutate()}>Save edits</button>}
                <button className="rounded border px-3 py-1 hover:bg-gray-100" disabled={text !== null} title={text !== null ? "Save your edits first" : ""} onClick={() => sign.mutate()}>Sign note</button>
              </div>
            </>
          ) : <p className="whitespace-pre-wrap rounded bg-gray-50 p-2">{note.body.text}</p>}
        </div>
      )}
      <div className="mt-3 flex items-center gap-2 text-sm">
        <input className="w-80 rounded border px-2 py-1" placeholder="Reason to escalate this patient" value={why} onChange={(e) => setWhy(e.target.value)} />
        <button className="rounded border px-3 py-1 hover:bg-gray-100 disabled:opacity-50" disabled={why.trim().length < 5} onClick={() => escalate.mutate()}>Escalate</button>
        {escalate.isSuccess && <span className="text-green-700">logged</span>}
      </div>
      {err && <p className="mt-1 text-sm text-red-700">{err.message}</p>}
      {evidence && <EvidencePanel findingId={evidence} onClose={() => setEvidence(null)} />}
    </section>
  );
}

export default function PatientPage() {
  const { id } = useParams<{ id: string }>();
  const { role } = useRole();
  const q = useQuery({ queryKey: ["profile", id, role], queryFn: () => api<Profile>(`/medical/patients/${id}/profile`, role) });
  if (q.error) return <main className="p-6 text-red-700">{(q.error as Error).message}</main>;
  if (!q.data) return <main className="p-6 text-gray-500">Loading…</main>;
  const p = q.data;
  const linkDays = p.links.map((l) => p.adverse_events.find((a) => a.id === l.ae_id)?.onset_at).filter(Boolean) as string[];
  return (
    <main className="space-y-4 p-6">
      <div>
        <h1 className="text-xl font-semibold font-mono">{p.subject.usubjid}</h1>
        <p className="text-sm text-gray-600">Site {p.subject.site_id} · {p.subject.age} y · {p.subject.sex} · status {p.subject.status} · first dose {p.subject.first_dose_at ?? "—"}</p>
        <div className="mt-1 flex flex-wrap gap-2">{p.flags.map((f, i) => (<span key={i} className="flex items-center gap-1 text-sm"><TypeBadge type={f.type} /> {f.title}</span>))}</div>
      </div>
      <Swimlanes p={p} />
      <NotePanel usubjid={p.subject.usubjid} />
      <div className="grid gap-3 md:grid-cols-2">
        {["ALT", "AST", "BILI", "ALP", "CREAT", "PLAT"].filter((t) => p.labs[t]).map((t) => (<LabChart key={t} test={t} rows={p.labs[t]} linkDays={linkDays} />))}
      </div>
      {p.links.length > 0 && (
        <section><h2 className="font-medium">Adverse events near a lab change</h2>
          <ul className="list-disc pl-5 text-sm">{p.links.map((l) => (<li key={`${l.lab_id}-${l.ae_id}`}>{l.ae_term.toLowerCase()} — {Math.abs(l.days_apart)} days {l.days_apart >= 0 ? "after" : "before"} the {l.test} change</li>))}</ul>
        </section>
      )}
      <section>
        <h2 className="font-medium">Adverse events</h2>
        <table className="text-sm"><thead className="text-left text-gray-500"><tr><th className="pr-4">Term</th><th className="pr-4">Onset</th><th className="pr-4">Grade</th><th className="pr-4">Serious</th><th>Outcome</th></tr></thead>
          <tbody>{p.adverse_events.map((a) => (<tr key={a.id}><td className="pr-4">{a.term_coded}</td><td className="pr-4 font-mono">{a.onset_at}</td><td className="pr-4">{a.ctcae_grade ?? "—"}</td><td className="pr-4">{a.serious ? "yes" : ""}</td><td>{a.outcome ?? "—"}</td></tr>))}</tbody>
        </table>
      </section>
    </main>
  );
}
