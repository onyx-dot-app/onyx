import type { WithoutStyles } from "@/types";

interface TableProps
  extends WithoutStyles<React.TableHTMLAttributes<HTMLTableElement>> {
  ref?: React.Ref<HTMLTableElement>;
}

function Table({ ref, ...props }: TableProps) {
  return (
    <table
      ref={ref}
      className="min-w-full border-collapse"
      style={{ tableLayout: "fixed" }}
      {...props}
    />
  );
}

export default Table;
export type { TableProps };
