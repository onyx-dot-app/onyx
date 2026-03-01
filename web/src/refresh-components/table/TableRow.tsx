import { cn } from "@/lib/utils";
import type { WithoutStyles } from "@/types";

interface TableRowProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableRowElement>> {
  ref?: React.Ref<HTMLTableRowElement>;
  selected?: boolean;
}

function TableRow({ selected, ref, ...props }: TableRowProps) {
  return <tr ref={ref} {...props} />;
}

export default TableRow;
export type { TableRowProps };
