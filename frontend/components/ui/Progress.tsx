import { cn } from "@/lib/cn";

export function Progress({ value, tone = "brand", className }: { value: number; tone?: "brand" | "success" | "danger"; className?: string }) {
  const safe = Math.min(100, Math.max(0, value));
  return <div className={cn("ui-progress", className)} role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(safe)}>
    <div className={cn("ui-progress-bar", `ui-progress-bar--${tone}`)} style={{ width: `${safe}%` }} />
  </div>;
}
