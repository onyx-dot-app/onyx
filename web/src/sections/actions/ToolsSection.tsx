"use client";

import React, { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import Button from "@/refresh-components/buttons/Button";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgRefreshCw from "@/icons/refresh-cw";
import SvgFold from "@/icons/fold";
import type { Tool } from "./ToolsList";

interface ToolsSectionProps {
  serverName: string;
  tools?: Tool[];
  onRefresh?: () => void;
  onDisableAll?: () => void;
  onFold?: () => void;
  onSearchChange?: (searchQuery: string, filteredTools: Tool[]) => void;
  className?: string;
}

const ToolsSection: React.FC<ToolsSectionProps> = ({
  serverName,
  tools,
  onRefresh,
  onDisableAll,
  onFold,
  onSearchChange,
  className,
}) => {
  const [searchQuery, setSearchQuery] = useState("");

  // Filter tools based on search query
  const filteredTools = useMemo(() => {
    if (!tools) return [];
    if (!searchQuery.trim()) return tools;

    const query = searchQuery.toLowerCase();
    return tools.filter(
      (tool) =>
        tool.name.toLowerCase().includes(query) ||
        tool.description.toLowerCase().includes(query)
    );
  }, [tools, searchQuery]);

  // Notify parent when search query or filtered tools change
  React.useEffect(() => {
    onSearchChange?.(searchQuery, filteredTools);
  }, [searchQuery, filteredTools, onSearchChange]);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setSearchQuery(e.target.value);
  };

  return (
    <div className={cn("w-full", className)}>
      <div className="flex gap-1 items-center w-full transition-all duration-300 ease-in-out px-2 pb-2">
        {/* Search Bar */}
        <div className="flex-1 min-w-[160px]">
          <InputTypeIn
            placeholder="Search tools…"
            value={searchQuery}
            onChange={handleSearchChange}
            leftSearchIcon
            showClearButton
            className="w-full"
          />
        </div>

        {/* Actions */}
        <div className="flex gap-1 items-center p-1">
          {/* Refresh Button */}
          {onRefresh && (
            <IconButton
              icon={SvgRefreshCw}
              onClick={onRefresh}
              tertiary
              tooltip="Refresh tools"
            />
          )}

          {/* Disable All Button */}
          {onDisableAll && (
            <Button tertiary onClick={onDisableAll}>
              Disable All
            </Button>
          )}

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
