"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { SvgFold } from "@opal/icons";
interface ToolsSectionProps {
  onFold?: () => void;
  searchQuery: string;
  onSearchQueryChange: (query: string) => void;
  className?: string;
}

const ToolsSection: React.FC<ToolsSectionProps> = ({
  onFold,
  searchQuery,
  onSearchQueryChange,
  className,
}) => {
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSearchQueryChange(e.target.value);
  };

  return (
    <div className={cn("w-full", className)}>
      <div className="flex gap-1 items-center w-full transition-all duration-300 ease-in-out px-2 pb-2">
        {/* Search Bar */}
        <div className="flex-1 min-w-[160px]">
          <InputTypeIn
            placeholder="Search tools…"
            aria-label="Search tools"
            value={searchQuery}
            onChange={handleSearchChange}
            leftSearchIcon
            showClearButton
            className="w-full"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-1 items-center p-1">
          {/* Fold Button */}
          {onFold && (
            <Button tertiary onClick={onFold} rightIcon={SvgFold}>
              Fold
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

ToolsSection.displayName = "ToolsSection";
export default ToolsSection;
