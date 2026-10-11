import * as React from "react";
import { cn } from "@/lib/cn";

export function Card({ className, ...props }: React.HTMLAttributes<HTMLElement>) {
  return <section className={cn("ui-card", className)} {...props} />;
}

export function CardHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("ui-card-header", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.HTMLAttributes<HTMLHeadingElement>) {
  return <h2 className={cn("ui-card-title", className)} {...props} />;
}

export function CardContent({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("ui-card-content", className)} {...props} />;
}
