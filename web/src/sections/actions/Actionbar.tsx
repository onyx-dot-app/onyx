"use client";

import React from "react";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import { SvgPlusCircle } from "@opal/icons";
interface ActionbarProps {
  hasActions: boolean;
  searchQuery?: string;
  onSearchQueryChange?: (query: string) => void;
  onAddAction: () => void;
  className?: string;
  buttonText?: string;
}

const Actionbar: React.FC<ActionbarProps> = ({
  hasActions,
  searchQuery = "",
  onSearchQueryChange,
  onAddAction,
  className,
  buttonText = "Add MCP Server",
}) => {
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onSearchQueryChange?.(e.target.value);
  };

  return (
    <div
      className={cn(
        "flex gap-4 items-center rounded-16",
        !hasActions ? "bg-background-tint-00 border border-border-01 p-4" : "",
        className
      )}
    >
      {hasActions ? (
        <div className="flex-1 min-w-[160px]">
          <InputTypeIn
            placeholder="Search servers…"
            value={searchQuery}
            onChange={handleSearchChange}
            leftSearchIcon
            showClearButton
            className="w-full !bg-transparent !border-transparent [&:is(:hover,:active,:focus,:focus-within)]:!bg-background-neutral-00 [&:is(:hover,:active,:focus,:focus-within)]:!border-border-01 [&:is(:focus,:focus-within)]:!shadow-none"
          />
        </div>
      ) : (
        <div className="flex-1">
          <Text as="p" mainUiMuted text03>
            Connect MCP server to add custom actions.
          </Text>
        </div>
      )}

      <div className="flex gap-2 items-center justify-end">
        <Button main primary leftIcon={SvgPlusCircle} onClick={onAddAction}>
          {buttonText}
        </Button>
      </div>
    </div>
  );
};

Actionbar.displayName = "Actionbar";
export default Actionbar;
