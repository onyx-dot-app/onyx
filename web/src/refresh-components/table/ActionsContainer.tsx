import { useTableSize } from "@/refresh-components/table/TableSizeContext";
import type { TableSize } from "@/refresh-components/table/TableSizeContext";

interface ActionsContainerProps {
  type: "head" | "cell";
  children: React.ReactNode;
  size?: TableSize;
  /** Pass-through click handler (e.g. stopPropagation on body cells). */
  onClick?: (e: React.MouseEvent) => void;
}

export default function ActionsContainer({
  type,
  children,
  size,
  onClick,
}: ActionsContainerProps) {
  const contextSize = useTableSize();
  const resolvedSize = size ?? contextSize;

  const Tag = type === "head" ? "th" : "td";

  return (
    <Tag
      className="tbl-actions"
      data-type={type}
      data-size={resolvedSize}
      onClick={onClick}
    >
      <div className="flex h-full items-center justify-center">{children}</div>
    </Tag>
  );
}
