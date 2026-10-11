"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useRole } from "@/components/Providers";
import { api, type QAResult } from "@/lib/api";

export default function AskPage() {
  const { role } = useRole();
  const qc = useQueryClient();
  const [q, setQ] = useState("");
  const [note, setNote] = useState<string | null>(null);
  const ask = useMutation({
    mutationFn: () => api<QAResult>("/protocol/ask", role, { method: "POST", body: JSON.stringify({ question: q }) }),
    onMutate: () => setNote(null),
  });
  const decide = useMutation({
    mutationFn: (action: "approve" | "reject") => api(`/drafts/${ask.data!.draft_id}/${action}`, role, { method: "POST", body: JSON.stringify({}) }),
    onSuccess: (_d, action) => { setNote(action === "approve" ? "Answer approved for sending." : "Answer rejected."); qc.invalidateQueries({ queryKey: ["drafts"] }); },
  });
  const escalate = useMutation({
    mutationFn: () => api("/medical/escalations", role, { method: "POST", body: JSON.stringify({ reason: `Protocol question needs a person: ${q}` }) }),
    onSuccess: () => { setNote("Escalation logged for the medical monitor."); qc.invalidateQueries({ queryKey: ["escalations"] }); },
  });
  const r = ask.data;
  return (
    <main className="max-w-3xl space-y-4 p-6">
      <h1 className="text-xl font-semibold">Ask the protocol</h1>
      <p className="text-sm text-gray-500">Answers come only from the protocol, with the exact wording quoted. If the protocol does not settle the question, or it needs a medical judgment about a patient, it says so and asks you to escalate. Answers are drafts: a person approves them before they are sent.</p>
      <form className="space-y-2" onSubmit={(e) => { e.preventDefault(); if (q.trim()) ask.mutate(); }}>
        <textarea className="h-20 w-full rounded border p-2 text-sm" placeholder="e.g. How long do we have to answer a query?" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="rounded border px-3 py-1 text-sm hover:bg-gray-100 disabled:opacity-50" disabled={ask.isPending}>{ask.isPending ? "Searching…" : "Ask"}</button>
      </form>
      {ask.error && <p className="text-red-700">{(ask.error as Error).message}</p>}
      {r && (
        <div className={`space-y-2 rounded border p-3 ${r.escalate ? "border-amber-400 bg-amber-50" : "border-green-300 bg-green-50"}`}>
          <div className="flex items-center gap-2 text-sm">
            <span className={`rounded px-2 py-0.5 font-medium ${r.escalate ? "bg-amber-200 text-amber-900" : "bg-green-200 text-green-900"}`}>{r.escalate ? "Escalate to a person" : "Answered from the protocol"}</span>
            <span className="text-gray-600">confidence {r.confidence.toFixed(2)} · {r.source === "gemini" ? "AI answer" : "text match"}</span>
          </div>
          <p>{r.answer}</p>
          {r.reason && <p className="text-sm text-amber-900">Why: {r.reason}</p>}
          {r.quotes.map((x) => (<blockquote key={x.chunk_id + x.text} className="border-l-4 pl-3 text-sm text-gray-700"><span className="font-mono text-xs text-gray-500">{x.section}</span><br />&ldquo;{x.text}&rdquo;</blockquote>))}
          <div className="flex flex-wrap items-center gap-2 pt-1 text-sm">
            <button className="rounded border bg-white px-3 py-1 hover:bg-gray-100" onClick={() => decide.mutate("approve")}>Approve to send</button>
            <button className="rounded border bg-white px-3 py-1 hover:bg-gray-100" onClick={() => decide.mutate("reject")}>Reject</button>
            <button className="rounded border bg-white px-3 py-1 hover:bg-gray-100" onClick={() => escalate.mutate()}>Log escalation</button>
            {note && <span className="text-gray-700">{note}</span>}
            {(decide.error || escalate.error) && <span className="text-red-700">{((decide.error ?? escalate.error) as Error).message}</span>}
          </div>
        </div>
      )}
    </main>
  );
}
