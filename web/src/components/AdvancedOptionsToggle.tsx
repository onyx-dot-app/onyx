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
    <Button
      type="button"
      variant="light"
      size="xs"
      icon={showAdvancedOptions ? FiChevronDown : FiChevronRight}
      onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
      className="mb-4 text-xs text-text-500 hover:text-text-400"
    >
      Advanced Options
    </Button>
  );
}
