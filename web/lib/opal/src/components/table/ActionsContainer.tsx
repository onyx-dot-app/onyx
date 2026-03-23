"use client";

import { useTableSize } from "@opal/components/table/TableSizeContext";

interface ActionsContainerProps {
  type: "head" | "cell";
  /** Pass-through click handler (e.g. stopPropagation on body cells). */
  onClick?: (e: React.MouseEvent) => void;
  children: React.ReactNode;
}

export default function ActionsContainer({
  type,
  children,
  onClick,
}: ActionsContainerProps) {
  const size = useTableSize();
  const Tag = type === "head" ? "th" : "td";

  return (
    <Tag
      className="tbl-actions"
      data-type={type}
      data-size={size}
      onClick={onClick}
    >
      <div className="flex h-full items-center justify-end">{children}</div>
    </Tag>
  );
}
