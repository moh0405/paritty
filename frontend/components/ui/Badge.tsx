import * as React from "react";
import { cn } from "@/lib/cn";

type Props = React.HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "info" | "success" | "warning" | "danger" };

export function Badge({ className, tone = "neutral", ...props }: Props) {
  return <span className={cn("ui-badge", `ui-badge--${tone}`, className)} {...props} />;
}
