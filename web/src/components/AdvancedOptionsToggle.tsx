import React from "react";
import Button from "@/refresh-components/buttons/Button";
import { FiChevronDown, FiChevronRight } from "react-icons/fi";

interface AdvancedOptionsToggleProps {
  showAdvancedOptions: boolean;
  setShowAdvancedOptions: (show: boolean) => void;
  title?: string;
}

export function AdvancedOptionsToggle({
  showAdvancedOptions,
  setShowAdvancedOptions,
  title,
}: AdvancedOptionsToggleProps) {
  return (
    <Button
      type="button"
      tertiary
      leftIcon={showAdvancedOptions ? FiChevronDown : FiChevronRight}
      onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
      className="text-xs mr-auto !p-0 text-text-950 hover:text-text-500"
    >
      {title || "Advanced Options"}
    </Button>
  );
}
