import React from "react";
import Button from "@/refresh-components/buttons/Button";
import { cn } from "@/lib/utils";
import SvgChevronRight from "@/icons/chevron-right";

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
      internal
      leftIcon={({ className }) => (
        <SvgChevronRight
          className={cn(className, showAdvancedOptions && "rotate-90")}
        />
      )}
      onClick={() => setShowAdvancedOptions(!showAdvancedOptions)}
      className="mr-auto"
    >
      {title || "Advanced Options"}
    </Button>
  );
}
