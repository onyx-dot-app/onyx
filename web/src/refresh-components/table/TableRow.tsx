import { cn } from "@/lib/utils";
import type { WithoutStyles } from "@/types";

interface TableRowProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableRowElement>> {
  ref?: React.Ref<HTMLTableRowElement>;
  selected?: boolean;
  size?: "regular" | "small";
}

function TableRow({ selected, ref, ...props }: TableRowProps) {
  const isSmall = props.size === "small";
  return (
    <tr ref={ref} className={cn(isSmall ? "py-1.5" : "py-0.5")} {...props} />
  );
}

export default TableRow;
export type { TableRowProps };
