import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type CardProps = HTMLAttributes<HTMLDivElement>;

export function Card({ className, ...props }: CardProps) {
  return (
    <div
      className={cn(
        "rounded-lg border border-slate-200 bg-white text-slate-950 shadow-sm",
        className
      )}
      {...props}
    />
  );
}

export type CardHeaderProps = HTMLAttributes<HTMLDivElement>;

export function CardHeader({ className, ...props }: CardHeaderProps) {
  return <div className={cn("flex flex-col space-y-1.5 p-6", className)} {...props} />;
}

export type CardTitleProps = HTMLAttributes<HTMLHeadingElement>;

export function CardTitle({ className, ...props }: CardTitleProps) {
  return (
    <h3 className={cn("text-2xl font-semibold leading-none tracking-tight", className)} {...props} />
  );
}

export type CardDescriptionProps = HTMLAttributes<HTMLParagraphElement>;

export function CardDescription({ className, ...props }: CardDescriptionProps) {
  return <p className={cn("text-sm text-slate-500", className)} {...props} />;
}

export type CardContentProps = HTMLAttributes<HTMLDivElement>;

export function CardContent({ className, ...props }: CardContentProps) {
  return <div className={cn("p-6 pt-0", className)} {...props} />;
}

export type CardFooterProps = HTMLAttributes<HTMLDivElement>;

export function CardFooter({ className, ...props }: CardFooterProps) {
  return <div className={cn("flex items-center p-6 pt-0", className)} {...props} />;
}