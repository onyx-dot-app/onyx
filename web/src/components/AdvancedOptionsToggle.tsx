import React from "react";
import { Button } from "@tremor/react";
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
        variant="light"
        size="xs"
        icon={showAdvancedOptions ? FiChevronDown : FiChevronRight}
        onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
        className="text-xs text-text-950 hover:text-text-500"
      >
        Advanced Options
      </Button>
    </div>
  );
}
