"use client";
import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { api, ROLE_LABELS, type Attention, type Role } from "@/lib/api";
import { useRole } from "./Providers";

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
        className={`flex items-center justify-between rounded-md px-3 py-2 ${active === href ? "bg-blue-50 font-semibold text-blue-700" : "text-gray-700 hover:bg-gray-100"}`}>
        <span>{label}</span>
        {badge ? <span className="rounded-full bg-blue-600 px-1.5 text-[11px] font-semibold leading-5 text-white" title="waiting for your decision">{badge}</span> : null}
      </Link>
    );
  };
  const badges = attention.data?.badges ?? {};
  const group = (id: string, title: string, keys: string[]) => {
    const waiting = keys.reduce((n, k) => n + (badges[ITEMS[k].href] ?? 0), 0);      // a closed group still shows that something in it waits for you
    return (
      <div>
        <button className="flex w-full items-center justify-between rounded-md px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-500 hover:bg-gray-100"
          aria-expanded={open(id, keys)} onClick={() => setToggled((t) => ({ ...t, [id]: !open(id, keys) }))}>
          <span>{title}</span>
          <span className="flex items-center gap-2">{!open(id, keys) && waiting > 0 && <span className="rounded-full bg-blue-100 px-1.5 text-[11px] leading-5 text-blue-700" title="waiting for your decision">{waiting}</span>}
            <span aria-hidden>{open(id, keys) ? "−" : "+"}</span></span>
        </button>
        {open(id, keys) && <div className="flex flex-col gap-1">{keys.map((k) => link(k, badges[ITEMS[k].href]))}</div>}
      </div>
    );
  };
  return (
    <aside className="sticky top-[56px] hidden h-[calc(100vh-56px)] w-56 shrink-0 flex-col overflow-y-auto border-r bg-white px-3 py-4 md:flex">
      <nav className="flex flex-col gap-1 text-sm">
        {link("today", attention.data?.decisions)}
        {link("lock")}
        <p className="mt-4 px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-gray-500">{ROLE_LABELS[role]}</p>
        {mine.map((k) => link(k, badges[ITEMS[k].href]))}
        <div className="mt-4 flex flex-col gap-1">
          {group("others", "Other areas", others)}
          {group("tools", "Tools", TOOLS)}
        </div>
      </nav>
      <p className="mt-auto px-3 pt-4 text-xs text-gray-500">All numbers click to evidence</p>
    </aside>
  );
}
