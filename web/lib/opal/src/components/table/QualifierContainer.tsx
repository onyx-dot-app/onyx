import { useTableSize } from "./TableSizeContext";
import type { TableSize } from "./TableSizeContext";

interface QualifierContainerProps {
  type: "head" | "cell";
  children?: React.ReactNode;
  size?: TableSize;
  /** Pass-through click handler (e.g. stopPropagation on body cells). */
  onClick?: (e: React.MouseEvent) => void;
}

export default function QualifierContainer({
  type,
  children,
  size,
  onClick,
}: QualifierContainerProps) {
  const contextSize = useTableSize();
  const resolvedSize = size ?? contextSize;

  const Tag = type === "head" ? "th" : "td";

  return (
    <Tag
      className="tbl-qualifier"
      data-type={type}
      data-size={resolvedSize}
      onClick={onClick}
    >
      <div className="flex h-full items-center justify-center">{children}</div>
    </Tag>
  );
}
