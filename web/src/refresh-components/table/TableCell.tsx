import { Content, type ContentProps } from "@opal/layouts/Content/components";

type TableCellProps =
  | (ContentProps & React.TdHTMLAttributes<HTMLTableCellElement>)
  | (React.TdHTMLAttributes<HTMLTableCellElement> & {
      children: React.ReactNode;
    });

export default function TableCell(props: TableCellProps) {
  if ("children" in props && props.children !== undefined) {
    return <td {...props} />;
  }

  return (
    <td {...(props as React.TdHTMLAttributes<HTMLTableCellElement>)}>
      <Content {...(props as ContentProps)} />
    </td>
  );
}

export type { TableCellProps };
