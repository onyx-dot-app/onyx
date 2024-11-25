import React from "react";
import { Button } from "@/components/ui/button";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";

interface AdvancedOptionsToggleProps {
  showAdvancedOptions: boolean;
  setShowAdvancedOptions: (show: boolean) => void;
}

export function AdvancedOptionsToggle({
  showAdvancedOptions,
  setShowAdvancedOptions,
}: AdvancedOptionsToggleProps) {
  return (
    <div>
      <Button
        type="button"
        variant="link"
        size="sm"
        icon={showAdvancedOptions ? FiChevronDown : FiChevronRight}
        onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
        className="text-xs text-text-950 hover:text-text-500"
      >
        Advanced Options
      </Button>
    </div>
  );
}
