import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <span aria-hidden="true" className={cn("ui-skeleton block", className)} />;
}
