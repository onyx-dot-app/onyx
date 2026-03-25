"use client";

import { useTableSize } from "@opal/components/table/TableSizeContext";

interface QualifierContainerProps {
  type: "head" | "cell";
  children?: React.ReactNode;
  /** Pass-through click handler (e.g. stopPropagation on body cells). */
  onClick?: (e: React.MouseEvent) => void;
}

export default function QualifierContainer({
  type,
  children,
  onClick,
}: QualifierContainerProps) {
  const resolvedSize = useTableSize();

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
