"use client";

import { cn } from "@opal/utils";
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
      <div
        className={cn(
          "flex h-full items-center",
          type === "cell" ? "justify-end" : "justify-center"
        )}
      >
        {children}
      </div>
    </Tag>
  );
}
