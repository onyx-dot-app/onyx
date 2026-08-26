"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { cn } from "@opal/utils";
import { Button } from "@opal/components";
import { InputTypeIn } from "@opal/components";
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
  const t = useTranslations("actions");

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSearchQueryChange(e.target.value);
  };

  return (
    <div className={cn("w-full", className)}>
      <div className="flex gap-1 items-center w-full transition-all duration-300 ease-in-out px-2 pb-2">
        {/* Search Bar */}
        <div className="flex-1 min-w-[160px]">
          <InputTypeIn
            placeholder={t("toolsSection.search.placeholder")}
            aria-label={t("toolsSection.search.ariaLabel")}
            value={searchQuery}
            onChange={handleSearchChange}
            searchIcon
            clearButton
          />
        </div>

        {/* Actions */}
        <div className="flex gap-1 items-center p-1">
          {/* Fold Button */}
          {onFold && (
            <Button prominence="tertiary" onClick={onFold} rightIcon={SvgFold}>
              {t("toolsSection.foldButton.label")}
            </Button>
          )}
        </div>
      </div>
    </div>
  );
};

ToolsSection.displayName = "ToolsSection";
export default ToolsSection;
