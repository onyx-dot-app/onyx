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
import ToolsList, { Tool } from "./ToolsList";

interface ToolsSectionProps {
  serverName: string;
  toolCount?: number;
  tools?: Tool[];
  onToolToggle?: (toolId: string, enabled: boolean) => void;
  onRefresh?: () => void;
  onDisableAll?: () => void;
  className?: string;
}

const ToolsSection: React.FC<ToolsSectionProps> = ({
  serverName,
  toolCount,
  tools,
  onToolToggle,
  onRefresh,
  onDisableAll,
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

  const handleToggle = () => {
    setIsExpanded(!isExpanded);
    if (!isExpanded) {
      setSearchQuery(""); // Reset search when expanding
    }
  };

  return (
    <div className={cn("w-full", className)}>
      {!isExpanded ? (
        // Collapsed State: Show tool count and View Tools button
        <div className="flex gap-2 items-center justify-end pl-8 w-full">
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
        </div>
      ) : (
        // Expanded State: Show search bar, actions, and tools list
        <div className="flex flex-col w-full">
          {/* Action Bar - replaces the collapsed view */}
          <div className="flex gap-1 items-center pl-8 w-full">
            {/* Search Bar */}
            <div className="flex-1 min-w-[160px]">
              <InputTypeIn
                placeholder="Search tools…"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                leftSearchIcon
                showClearButton
                className="w-full shadow-[0px_0px_0px_2px_var(--background-tint-04)]"
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
                <button
                  onClick={onDisableAll}
                  className="flex items-center justify-center overflow-hidden p-1 rounded-08 hover:bg-background-tint-02"
                >
                  <div className="flex gap-1 items-center px-1 py-0.5">
                    <Text text03 secondaryAction className="text-center">
                      Disable All
                    </Text>
                  </div>
                </button>
              )}

              {/* Fold Button */}
              <button
                onClick={handleToggle}
                className="flex items-center justify-center overflow-hidden p-1 rounded-08 hover:bg-background-tint-02"
              >
                <div className="flex gap-1 items-center pl-1 pr-0.5 py-0.5">
                  <Text text03 secondaryAction className="text-right">
                    Fold
                  </Text>
                </div>
                <div className="flex items-center p-0.5 w-5 h-5">
                  <SvgFold className="w-4 h-4 stroke-text-03" />
                </div>
              </button>
            </div>
          </div>

          {/* Tools List */}
          <ToolsList
            tools={filteredTools}
            searchQuery={searchQuery}
            onToolToggle={onToolToggle}
          />
        </div>
      )}
    </div>
  );
};

ToolsSection.displayName = "ToolsSection";
export default ToolsSection;
