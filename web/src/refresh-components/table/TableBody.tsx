import type { WithoutStyles } from "@/types";

interface TableBodyProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableSectionElement>> {
  ref?: React.Ref<HTMLTableSectionElement>;
}

function TableBody({ ref, ...props }: TableBodyProps) {
  return <tbody ref={ref} {...props} />;
}

export default TableBody;
export type { TableBodyProps };
