import type { WithoutStyles } from "@opal/types";

interface TableHeaderProps
  extends WithoutStyles<React.HTMLAttributes<HTMLTableSectionElement>> {
  ref?: React.Ref<HTMLTableSectionElement>;
}

function TableHeader({ ref, ...props }: TableHeaderProps) {
  return <thead ref={ref} {...props} />;
}

export default TableHeader;
export type { TableHeaderProps };
