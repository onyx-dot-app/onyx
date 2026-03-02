import { cn } from "@/lib/utils";
import type { WithoutStyles } from "@/types";

interface TableCellProps
  extends WithoutStyles<React.TdHTMLAttributes<HTMLTableCellElement>> {
  children: React.ReactNode;
  size?: "regular" | "small";
}

export default function TableCell({
  size = "regular",
  children,
  ...props
}: TableCellProps) {
  const isSmall = size === "small";
  return (
    <td
      className={cn(isSmall ? "pl-0.5 pr-1.5 py-1.5" : "px-1 py-0.5")}
      {...props}
    >
      <div
        className={cn(
          "flex items-center",
          isSmall ? "h-6 px-0.5" : "h-10 px-1"
        )}
      >
        {children}
      </div>
    </td>
  );
}

export type { TableCellProps };
