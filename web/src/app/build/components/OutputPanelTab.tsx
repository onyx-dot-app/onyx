"use client";

import { cn } from "@/lib/utils";
import { SvgChevronLeft } from "@opal/icons";

interface OutputPanelTabProps {
  isOpen: boolean;
  onClick: () => void;
}

/**
 * OutputPanelTab - A tab button that opens/closes the output panel
 * Looks like a folder tab that extends slightly on hover
 * Features rotating chevron for directional feedback
 */
export default function OutputPanelTab({
  isOpen,
  onClick,
}: OutputPanelTabProps) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center justify-center py-12",
        "border border-border-01",
        "bg-background-neutral-00 hover:bg-background-neutral-01",
        "transition-all duration-200 ease-in-out",
        // Rounded on left side only (folder tab shape)
        "rounded-l-12 rounded-r-0 border-r-0",
        // Slight expansion on hover
        isOpen ? "px-2.5 hover:px-2" : "px-2.5 hover:px-3.5"
      )}
      aria-label={isOpen ? "Close output panel" : "Open output panel"}
    >
      <SvgChevronLeft
        size={16}
        className={cn(
          "stroke-text-04",
          // Points left when closed (open panel), right when open (close panel)
          isOpen && "rotate-180"
        )}
      />
    </button>
  );
}
