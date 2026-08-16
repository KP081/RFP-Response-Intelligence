import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: "default" | "secondary" | "outline" | "destructive" | "success";
}

export function Badge({ className, variant = "default", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold transition-colors",
        {
          "bg-slate-100 text-slate-800": variant === "default",
          "bg-blue-100 text-blue-800": variant === "secondary",
          "border border-slate-300 bg-transparent text-slate-700": variant === "outline",
          "bg-red-100 text-red-800": variant === "destructive",
          "bg-green-100 text-green-800": variant === "success",
        },
        className
      )}
      {...props}
    />
  );
}

export function getRoleBadgeVariant(role: string): BadgeProps["variant"] {
  switch (role) {
    case "admin":
      return "destructive";
    case "proposal_manager":
    case "presales_architect":
      return "secondary";
    case "sales":
    case "legal":
    case "security":
    case "compliance":
      return "default";
    case "viewer":
      return "outline";
    default:
      return "default";
  }
}

export function getRoleDisplayName(role: string): string {
  return role.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}