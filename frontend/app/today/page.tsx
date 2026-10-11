"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useRole } from "@/components/Providers";
import { startTour } from "@/components/Tour";
import { api, ROLE_LABELS, type Attention, type AttentionItem } from "@/lib/api";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Icon } from "@/components/ui/Icon";
import { StatCard } from "@/components/ui/StatCard";

function Row({ item }: { item: AttentionItem }) {
  return (
    <li className="group grid grid-cols-[auto_1fr] items-center gap-x-3 gap-y-3 border-t border-slate-100 py-4 first:border-t-0 sm:flex sm:gap-4">
      <span className={`grid h-10 w-10 shrink-0 place-items-center rounded-xl text-lg font-bold ${item.kind === "decide" ? "bg-teal-50 text-teal-800" : "bg-slate-100 text-slate-600"}`}>{item.count}</span>
      <div className="min-w-0 flex-1">
        <p className="font-semibold first-letter:uppercase">{item.title.replace(/^\d+\s/, "")}</p>
        <p className="text-sm text-gray-500">{item.help}</p>
      </div>
      <Link href={item.href} className="ui-button ui-button--outline ui-button--sm col-start-2 w-fit shrink-0 sm:col-auto">Open <Icon name="arrow" className="h-4 w-4" /></Link>
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
    <main className="space-y-6 p-6 lg:p-8">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>Today</h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-slate-500">Your focused work queue as {ROLE_LABELS[role].toLowerCase()}{q.data ? ` for ${q.data.today}` : ""}. Review decisions, risks, and lock readiness in one place.</p>
        </div>
        <Button variant="outline" onClick={startTour}><Icon name="sparkles" className="h-4 w-4 text-cyan-700" /> Take the 2-minute tour</Button>
      </div>
      {q.error && <p className="text-red-700">{(q.error as Error).message}</p>}
      <div className="grid gap-5 md:grid-cols-3">
        <StatCard label="Decisions waiting" icon="alert" accent="amber" loading={!q.data} value={q.data?.decisions}
          description={decide.length === 0 ? "You are up to date." : `Across ${decide.length} kind${decide.length === 1 ? "" : "s"} of work`} />
        <StatCard label="Most likely lock date" icon="calendar" loading={!q.data} value={lock?.p50 ?? "–"}
          description={lock ? <>Likely between {lock.p10} and {lock.p90}. <Link className="font-medium text-cyan-700 hover:underline" href="/">View blockers</Link></> : "Advance the clock to get a forecast."} />
        <StatCard label="Ready to lock" icon="shield" accent="emerald" loading={!q.data} value={lock ? `${lock.met} of ${lock.total}` : "–"}
          description="Conditions for locking the database are met" />
      </div>
      <Card>
        <CardHeader><CardTitle>Needs your decision</CardTitle>{decide.length > 0 && <Badge tone="info">{decide.reduce((n, item) => n + item.count, 0)} open</Badge>}</CardHeader>
        <CardContent>
        {decide.length === 0 ? <p className="mt-3 text-sm text-gray-500">Nothing is waiting for your decision. Advance the clock in the top bar and new work will arrive.</p>
          : <ul className="mt-1">{decide.map((i) => (<Row key={i.key} item={i} />))}</ul>}
        </CardContent>
      </Card>
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
