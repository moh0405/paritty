import * as React from "react";
import { cn } from "@/lib/cn";
import { Card, CardTitle } from "./Card";
import { Icon, type IconName } from "./Icon";
import { Skeleton } from "./Skeleton";

type Props = {
  label: string;
  value?: React.ReactNode;
  description: React.ReactNode;
  icon: IconName;
  accent?: "cyan" | "emerald" | "amber";
  loading?: boolean;
};

const tones = {
  cyan: "bg-cyan-50 text-cyan-700 ring-cyan-100",
  emerald: "bg-emerald-50 text-emerald-700 ring-emerald-100",
  amber: "bg-amber-50 text-amber-700 ring-amber-100",
};

export function StatCard({ label, value, description, icon, accent = "cyan", loading }: Props) {
  return <Card className="group relative overflow-hidden">
    <div className="flex items-start justify-between gap-4">
      <CardTitle>{label}</CardTitle>
      <span className={cn("grid h-9 w-9 place-items-center rounded-xl ring-1 transition-transform duration-200 group-hover:scale-105", tones[accent])}><Icon name={icon} className="h-4.5 w-4.5" /></span>
    </div>
    {loading ? <Skeleton className="mt-4 h-10 w-2/3" /> : <p className="mt-3 text-4xl font-bold tracking-[-.04em] tabular-nums text-slate-900">{value}</p>}
    <div className="mt-1 text-sm leading-relaxed text-slate-500">{description}</div>
  </Card>;
}
