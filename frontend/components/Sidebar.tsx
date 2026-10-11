"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { api, ROLE_LABELS, type Attention, type Role } from "@/lib/api";
import { useRole } from "./Providers";
import { Badge } from "./ui/Badge";
import { Icon, type IconName } from "./ui/Icon";

const ICONS: Record<string, IconName> = { today: "home", lock: "target", queries: "arrow", checks: "check", sae: "shield", labs: "labs", medical: "heart", liver: "activity", trends: "trend", ask: "file", sites: "users", plan: "calendar", agent: "sparkles", hub: "database", search: "search", evals: "check" };

// Plain names in the menu; the term a trial team would use is the tooltip.
type Item = { href: string; label: string; term?: string };
const ITEMS: Record<string, Item> = {
  today: { href: "/today", label: "Today" },
  lock: { href: "/", label: "Lock readiness", term: "Database lock forecast" },
  queries: { href: "/queries", label: "Queries to sites" },
  checks: { href: "/checks", label: "Data checks", term: "Edit checks" },
  sae: { href: "/recon/sae", label: "Safety report matching", term: "SAE reconciliation" },
  labs: { href: "/recon/labs", label: "Lab matching", term: "Central lab reconciliation" },
  medical: { href: "/medical", label: "Medical review" },
  liver: { href: "/medical/liver", label: "Liver safety", term: "eDISH plot" },
  trends: { href: "/medical/trends", label: "Lab trends" },
  ask: { href: "/ask", label: "Ask the protocol" },
  sites: { href: "/sites", label: "Site risk", term: "Key risk indicators (KRIs)" },
  plan: { href: "/sites/visit-plan", label: "Visit plan" },
  agent: { href: "/agent", label: "Suggested actions", term: "Data-manager agent" },
  hub: { href: "/hub", label: "Data hub" },
  search: { href: "/search", label: "Term search" },
  evals: { href: "/evals", label: "Accuracy tests", term: "Evaluations" },
};
const ALWAYS = ["today", "lock"];
const TOOLS = ["hub", "search", "evals"];
// The pages each role works in day to day. Everything else stays one click away under "Other areas".
const MINE: Record<Role, string[]> = {
  data_manager: ["queries", "checks", "sae", "labs"],
  medical_monitor: ["medical", "liver", "trends", "ask"],
  central_monitor: ["sites", "plan"],
  study_lead: ["agent"],
  unblinded_statistician: ["liver"],
};

export function Sidebar() {
  const path = usePathname();
  const { role } = useRole();
  const [toggled, setToggled] = useState<Record<string, boolean>>({});
  const attention = useQuery({ queryKey: ["attention", role], queryFn: () => api<Attention>("/attention", role), refetchInterval: 30000 });
  const mine = MINE[role] ?? [];
  const others = Object.keys(ITEMS).filter((k) => !ALWAYS.includes(k) && !TOOLS.includes(k) && !mine.includes(k));
  const active = Object.values(ITEMS).filter(({ href }) => (href === "/" ? path === "/" : path === href || path.startsWith(href + "/")))
    .sort((a, b) => b.href.length - a.href.length)[0]?.href;
  const holdsActive = (keys: string[]) => keys.some((k) => ITEMS[k].href === active);
  const open = (id: string, keys: string[]) => toggled[id] ?? holdsActive(keys);      // a group opens by itself when you are on one of its pages

  const link = (k: string, badge?: number) => {
    const { href, label, term } = ITEMS[k];
    return (
      <Link key={k} href={href} title={term}
        className={`group flex min-h-10 items-center justify-between rounded-lg px-3 py-2 transition-colors ${active === href ? "bg-teal-50 font-semibold text-teal-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"}`}>
        <span className="flex items-center gap-3"><span className={`grid h-7 w-7 place-items-center rounded-lg ${active === href ? "bg-white text-cyan-700 shadow-sm" : "text-slate-400 group-hover:text-slate-600"}`}><Icon name={ICONS[k]} className="h-4 w-4" /></span>{label}</span>
        {badge ? <Badge tone="info" title="waiting for your decision">{badge}</Badge> : null}
      </Link>
    );
  };
  const badges = attention.data?.badges ?? {};
  const group = (id: string, title: string, keys: string[]) => {
    const waiting = keys.reduce((n, k) => n + (badges[ITEMS[k].href] ?? 0), 0);      // a closed group still shows that something in it waits for you
    return (
      <div>
        <button className="flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-[10px] font-bold uppercase tracking-[.12em] text-slate-400 hover:bg-slate-100"
          aria-expanded={open(id, keys)} onClick={() => setToggled((t) => ({ ...t, [id]: !open(id, keys) }))}>
          <span>{title}</span>
          <span className="flex items-center gap-2">{!open(id, keys) && waiting > 0 && <span className="rounded-full bg-teal-100 px-1.5 text-[11px] leading-5 text-teal-700" title="waiting for your decision">{waiting}</span>}
            <Icon name="chevron" className={`h-3.5 w-3.5 transition-transform ${open(id, keys) ? "rotate-90" : ""}`} /></span>
        </button>
        {open(id, keys) && <div className="flex flex-col gap-1">{keys.map((k) => link(k, badges[ITEMS[k].href]))}</div>}
      </div>
    );
  };
  const mobileKeys = ["today", "lock", ...mine.slice(0, 2)];
  return <>
    <aside className="sticky top-16 hidden h-[calc(100vh-64px)] w-64 shrink-0 flex-col overflow-y-auto border-r border-slate-200/80 bg-white/90 px-3 py-5 backdrop-blur-xl md:flex">
      <nav className="flex flex-col gap-1 text-sm">
        {link("today", attention.data?.decisions)}
        {link("lock")}
        <p className="mt-5 px-3 pb-1 text-[10px] font-bold uppercase tracking-[.12em] text-slate-400">Your workspace · {ROLE_LABELS[role]}</p>
        {mine.map((k) => link(k, badges[ITEMS[k].href]))}
        <div className="mt-4 flex flex-col gap-1">
          {group("others", "Other areas", others)}
          {group("tools", "Tools", TOOLS)}
        </div>
      </nav>
      <div className="mt-auto rounded-xl border border-teal-100 bg-teal-50/70 p-3 text-xs leading-relaxed text-teal-900"><span className="mb-1 block font-semibold">Evidence built in</span>Every number links back to its source.</div>
    </aside>
    <nav aria-label="Primary navigation" className="fixed inset-x-3 bottom-3 z-30 grid grid-cols-4 rounded-2xl border border-slate-200/80 bg-white/95 p-1.5 shadow-[0_12px_40px_rgba(15,23,42,.18)] backdrop-blur-xl md:hidden">
      {mobileKeys.map((k) => {
        const item = ITEMS[k], current = active === item.href;
        return <Link key={k} href={item.href} aria-current={current ? "page" : undefined} className={`relative flex min-h-12 flex-col items-center justify-center gap-0.5 rounded-xl px-1 text-[10px] font-semibold transition-colors ${current ? "bg-cyan-50 text-cyan-800" : "text-slate-500 active:bg-slate-100"}`}>
          <Icon name={ICONS[k]} className="h-5 w-5" />
          <span className="max-w-full truncate">{item.label}</span>
          {!!badges[item.href] && <span className="absolute right-2 top-1.5 h-2 w-2 rounded-full bg-amber-500 ring-2 ring-white"><span className="sr-only">{badges[item.href]} items waiting</span></span>}
        </Link>;
      })}
    </nav>
  </>;
}
