"use client";

import React, { useState, useMemo } from "react";
import { cn } from "@/lib/utils";
import SvgChevronDown from "@/icons/chevron-down";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import SvgRefreshCw from "@/icons/refresh-cw";
import SvgFold from "@/icons/fold";
import type { Tool } from "./ToolsList";

interface ToolsSectionProps {
  serverName: string;
  toolCount?: number;
  tools?: Tool[];
  onRefresh?: () => void;
  onDisableAll?: () => void;
  onExpandedChange?: (
    isExpanded: boolean,
    searchQuery: string,
    filteredTools: Tool[]
  ) => void;
  className?: string;
}

const ToolsSection: React.FC<ToolsSectionProps> = ({
  serverName,
  toolCount,
  tools,
  onRefresh,
  onDisableAll,
  onExpandedChange,
  className,
}) => {
  const [isExpanded, setIsExpanded] = useState(false);
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

  // Notify parent when expanded state or filtered tools change
  React.useEffect(() => {
    onExpandedChange?.(isExpanded, searchQuery, filteredTools);
  }, [isExpanded, searchQuery, filteredTools, onExpandedChange]);

  const handleToggle = () => {
    const newExpanded = !isExpanded;
    setIsExpanded(newExpanded);
    if (newExpanded) {
      setSearchQuery(""); // Reset search when expanding
    }
  };

  return (
    <div className={cn("w-full", className)}>
      <div
        className={cn(
          "flex gap-1 items-center w-full transition-all duration-300 ease-in-out",
          !isExpanded && "pl-8 gap-2 justify-end"
        )}
      >
        {!isExpanded ? (
          // Collapsed State: Tool count and View Tools button
          <>
            <div className="flex flex-1 min-w-0 px-0.5">
              <Text mainUiAction text04 className="flex-1 min-w-0">
                {toolCount !== undefined
                  ? `${toolCount} tool${toolCount !== 1 ? "s" : ""}`
                  : "0 tools"}
              </Text>
            </div>
            <Button
              tertiary
              onClick={handleToggle}
              rightIcon={SvgChevronDown}
              className="shrink-0"
              aria-label={`View tools for ${serverName}`}
            >
              View Tools
            </Button>
          </>
        ) : (
          // Expanded State: Search bar and action buttons
          <>
            {/* Search Bar */}
            <div className="flex-1 min-w-[160px]">
              <InputTypeIn
                placeholder="Search tools…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
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
              <Button tertiary onClick={handleToggle} rightIcon={SvgFold}>
                Fold
              </Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
};

ToolsSection.displayName = "ToolsSection";
export default ToolsSection;
