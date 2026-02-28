import { cn } from "@/lib/utils";
import type { WithoutStyles } from "@/types";

interface TableCellProps
  extends WithoutStyles<React.TdHTMLAttributes<HTMLTableCellElement>> {
  children: React.ReactNode;
  size?: "regular" | "small";
}

export default function TableCell({
  size = "regular",
  ...props
}: TableCellProps) {
  const isSmall = size === "small";
  return (
    <td
      className={cn(isSmall ? "h-6 px-1 my-1.5" : "h-10 px-1.5 py-1")}
      {...props}
    />
  );
}

export type { TableCellProps };
