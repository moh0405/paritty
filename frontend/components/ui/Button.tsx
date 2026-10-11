import * as React from "react";
import { cn } from "@/lib/cn";

type Props = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "outline";
  size?: "sm" | "md" | "icon";
};

export function Button({ className, variant = "primary", size = "md", ...props }: Props) {
  return <button className={cn("ui-button", `ui-button--${variant}`, `ui-button--${size}`, className)} {...props} />;
}
