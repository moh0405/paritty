"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { useRole } from "@/components/Providers";
import { api, type TermHit, type TermSearch } from "@/lib/api";

function Column({ title, hits, fused }: { title: string; hits: TermHit[]; fused?: boolean }) {
  return (
    <div className="flex-1 rounded border p-2">
      <h3 className="mb-1 font-medium">{title}</h3>
      <ol className="space-y-0.5 text-sm">
        {hits.map((h) => (
          <li key={h.id} className="flex justify-between gap-2">
            <span>{h.rank}. {h.term}{h.coded_term !== h.term && <span className="text-gray-500"> → {h.coded_term}</span>}</span>
            <span className="font-mono text-xs text-gray-500">{fused ? h.score.toFixed(4) : h.score.toFixed(2)}</span>
          </li>
        ))}
        {hits.length === 0 && <li className="text-gray-500">no hits</li>}
      </ol>
    </div>
  );
}

export default function SearchPage() {
  const { role } = useRole();
  const [text, setText] = useState("heart attack");
  const [q, setQ] = useState("heart attack");
  const res = useQuery({ queryKey: ["terms", q, role], queryFn: () => api<TermSearch>(`/search/terms?q=${encodeURIComponent(q)}`, role), enabled: q.length > 0 });
  return (
    <main className="space-y-4 p-6">
      <h1 className="text-xl font-semibold">Adverse event term search</h1>
      <p className="text-sm text-gray-500">Keyword (BM25) and meaning (vector) results, combined by reciprocal rank fusion.</p>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); setQ(text.trim()); }}>
        <input className="w-80 rounded border px-2 py-1" value={text} onChange={(e) => setText(e.target.value)} placeholder="e.g. heart attack" />
        <button className="rounded border px-3 py-1 hover:bg-gray-100">Search</button>
      </form>
      {res.error && <p className="text-red-700">{(res.error as Error).message}</p>}
      {res.data && (
        <>
          <p className="text-sm text-gray-600">Method: {res.data.method}</p>
          <div className="flex flex-wrap gap-3">
            <Column title="BM25 (keywords)" hits={res.data.bm25} />
            <Column title="Vector (meaning)" hits={res.data.vector} />
            <Column title="Fused (RRF)" hits={res.data.fused} fused />
          </div>
        </>
      )}
    </main>
  );
}
