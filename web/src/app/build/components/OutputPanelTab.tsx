"use client";

import { cn } from "@/lib/utils";
import { SvgSidebar } from "@opal/icons";

interface OutputPanelTabProps {
  isOpen: boolean;
  onClick: () => void;
}

/**
 * OutputPanelTab - A tab button that opens/closes the output panel
 * Looks like a folder tab that extends slightly on hover
 */
export default function OutputPanelTab({
  isOpen,
  onClick,
}: OutputPanelTabProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center justify-center py-4",
        "border border-border-01",
        "bg-background-neutral-00 hover:bg-background-neutral-01",
        "transition-all duration-200 ease-in-out",
        // Rounded on left side only (folder tab shape)
        "rounded-l-12 rounded-r-0 border-r-0",
        // Slight expansion on hover
        isOpen ? "px-2.5" : "px-2 hover:px-3"
      )}
      aria-label={isOpen ? "Close output panel" : "Open output panel"}
    >
      <SvgSidebar className="size-4 stroke-text-03" />
    </button>
  );
}
