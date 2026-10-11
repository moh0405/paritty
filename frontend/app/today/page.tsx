"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRole } from "@/components/Providers";
import { startTour } from "@/components/Tour";
import { api, ROLE_LABELS, type Attention, type AttentionItem } from "@/lib/api";

function Row({ item }: { item: AttentionItem }) {
  return (
    <li className="flex items-center gap-4 border-t py-3 first:border-t-0">
      <span className={`w-12 shrink-0 text-right text-2xl font-bold ${item.kind === "decide" ? "text-blue-700" : "text-gray-500"}`}>{item.count}</span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold first-letter:uppercase">{item.title.replace(/^\d+\s/, "")}</p>
        <p className="text-sm text-gray-500">{item.help}</p>
      </div>
      <Link href={item.href} className="shrink-0 rounded-md border px-3 py-1.5 text-sm font-medium hover:bg-gray-100">Open</Link>
    </li>
  );
}

export default function TodayPage() {
  const { role } = useRole();
  const q = useQuery({ queryKey: ["attention", role], queryFn: () => api<Attention>("/attention", role) });
  const items = q.data?.items ?? [];
  const decide = items.filter((i) => i.mine && i.kind === "decide");
  const watch = items.filter((i) => i.mine && i.kind === "watch");
  const others = items.filter((i) => !i.mine);
  const lock = q.data?.lock;
  return (
    <main className="space-y-5 p-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>Today</h1>
          <p className="mt-1 text-sm text-gray-500">What is waiting for you as {ROLE_LABELS[role].toLowerCase()}{q.data ? ` on ${q.data.today}` : ""}. Nothing here happens by itself: every item needs a person.</p>
        </div>
        <button className="rounded-md border bg-white px-3 py-1.5 text-sm font-medium hover:bg-gray-100" onClick={startTour}>New here? Take the 2-minute tour</button>
      </div>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      <div className="grid gap-5 md:grid-cols-3">
        <section>
          <h2>Decisions waiting for you</h2>
          <p className="mt-2 text-4xl font-bold text-blue-700">{q.data ? q.data.decisions : "–"}</p>
          <p className="text-sm text-gray-500">{decide.length === 0 ? "You are up to date." : `across ${decide.length} kind${decide.length === 1 ? "" : "s"} of work`}</p>
        </section>
        <section>
          <h2>Most likely lock date</h2>
          <p className="mt-2 text-4xl font-bold">{lock ? lock.p50 : "–"}</p>
          <p className="text-sm text-gray-500">{lock ? <>likely between {lock.p10} and {lock.p90}. <Link className="text-blue-700 hover:underline" href="/">See what is holding it back</Link></> : "Advance the clock to get a forecast."}</p>
        </section>
        <section>
          <h2>Ready to lock</h2>
          <p className="mt-2 text-4xl font-bold">{lock ? `${lock.met} of ${lock.total}` : "–"}</p>
          <p className="text-sm text-gray-500">conditions for locking the database are met</p>
        </section>
      </div>
      <section>
        <h2>Needs your decision</h2>
        {decide.length === 0 ? <p className="mt-3 text-sm text-gray-500">Nothing is waiting for your decision. Advance the clock in the top bar and new work will arrive.</p>
          : <ul className="mt-1">{decide.map((i) => (<Row key={i.key} item={i} />))}</ul>}
      </section>
      {watch.length > 0 && (
        <section>
          <h2>Keep an eye on</h2>
          <ul className="mt-1">{watch.map((i) => (<Row key={i.key} item={i} />))}</ul>
        </section>
      )}
      {others.length > 0 && (
        <details className="rounded-xl border border-gray-200 bg-white p-5">
          <summary className="cursor-pointer text-sm font-medium text-gray-700">Waiting for other roles ({others.reduce((a, i) => a + i.count, 0)})</summary>
          <ul className="mt-3 space-y-1 text-sm text-gray-600">{others.map((i) => (
            <li key={i.key}><b>{i.count}</b> {i.title.replace(/^\d+\s/, "")} <span className="text-gray-400">({i.roles.map((r) => ROLE_LABELS[r]).join(", ")})</span></li>))}</ul>
          <p className="mt-3 text-xs text-gray-500">Switch role in the top bar to act on these.</p>
        </details>
      )}
    </main>
  );
}
