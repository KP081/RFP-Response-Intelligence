import type { HTMLAttributes } from "react";

import { cn } from "@/lib/utils";

export type TableProps = HTMLAttributes<HTMLTableElement>;

export function Table({ className, ...props }: TableProps) {
  return (
    <div className="rounded-md border border-slate-200 overflow-hidden">
      <table className={cn("w-full caption-bottom text-sm", className)} {...props} />
    </div>
  );
}

export type TableHeaderProps = HTMLAttributes<HTMLTableSectionElement>;

export function TableHeader({ className, ...props }: TableHeaderProps) {
  return <thead className={cn("[&_tr]:border-b", className)} {...props} />;
}

export type TableBodyProps = HTMLAttributes<HTMLTableSectionElement>;

export function TableBody({ className, ...props }: TableBodyProps) {
  return <tbody className={cn("[&_tr:last-child]:border-0", className)} {...props} />;
}

export type TableRowProps = HTMLAttributes<HTMLTableRowElement>;

export function TableRow({ className, ...props }: TableRowProps) {
  return (
    <tr
      className={cn(
        "border-b border-slate-200 transition-colors hover:bg-slate-50 data-[state=selected]:bg-slate-100",
        className
      )}
      {...props}
    />
  );
}

export type TableHeadProps = HTMLAttributes<HTMLTableCellElement>;

export function TableHead({ className, ...props }: TableHeadProps) {
  return (
    <th
      className={cn(
        "h-12 px-4 text-left align-middle font-medium text-slate-500 [&:has([role=checkbox])]:pr-0",
        className
      )}
      {...props}
    />
  );
}

export type TableCellProps = HTMLAttributes<HTMLTableCellElement> & {
  colSpan?: number;
};

export function TableCell({ className, colSpan, ...props }: TableCellProps) {
  return (
    <td colSpan={colSpan} className={cn("p-4 align-middle [&:has([role=checkbox])]:pr-0", className)} {...props} />
  );
}