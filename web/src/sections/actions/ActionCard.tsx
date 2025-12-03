"use client";

import React, { useState, useMemo } from "react";
import SvgServer from "@/icons/server";
import ActionCardHeader from "./ActionCardHeader";
import MCPActions from "./MCPActions";
import ToolsSection from "./ToolsSection";
import ToolsList, { Tool } from "./ToolsList";
import { cn } from "@/lib/utils";
import type { MCPActionStatus } from "./types";

export interface ActionCardProps {
  // Core content
  title: string;
  description: string;
  logo?: React.ReactNode;

  // Status
  status?: MCPActionStatus;

  // Tool count (only for connected state)
  toolCount?: number;

  // Tools (optional - for expanded view)
  tools?: Tool[];

  // Actions
  onDisconnect?: () => void;
  onManage?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onAuthenticate?: () => void; // For pending state
  onReconnect?: () => void; // For disconnected state

  // Tool-related actions
  onToolToggle?: (toolId: string, enabled: boolean) => void;
  onRefreshTools?: () => void;
  onDisableAllTools?: () => void;

  // Optional styling
  className?: string;
}

// Main Component
export default function ActionCard({
  title,
  description,
  logo,
  status = "connected",
  toolCount,
  tools,
  onDisconnect,
  onManage,
  onEdit,
  onDelete,
  onAuthenticate,
  onReconnect,
  onToolToggle,
  onRefreshTools,
  onDisableAllTools,
  className,
}: ActionCardProps) {
  const [isToolsExpanded, setIsToolsExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const isConnected = status === "connected";
  const isPending = status === "pending";
  const isDisconnected = status === "disconnected";

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

  const icon = isConnected ? (
    logo
  ) : (
    <SvgServer className="h-5 w-5 stroke-text-04" aria-hidden="true" />
  );

  const backgroundColor = isConnected
    ? "bg-background-tint-00"
    : isDisconnected
      ? "bg-background-neutral-02"
      : "";

  const handleToggleTools = () => {
    setIsToolsExpanded(!isToolsExpanded);
    if (isToolsExpanded) {
      setSearchQuery("");
    }
  };

  const handleFold = () => {
    setIsToolsExpanded(false);
    setSearchQuery("");
  };

  return (
    <div
      className={cn(
        "w-full",
        backgroundColor,
        "border border-border-01 rounded-16",
        className
      )}
      role="article"
      aria-label={`${title} MCP server card`}
    >
      <div className="flex flex-col w-full">
        {/* Header Section */}
        <div className="flex items-start justify-between pb-2 pl-3 pt-3 pr-2 w-full">
          <ActionCardHeader
            title={title}
            description={description}
            icon={icon}
            status={status}
            onEdit={onEdit}
          />

          {/* Action Buttons */}
          <MCPActions
            status={status}
            serverName={title}
            onDisconnect={onDisconnect}
            onManage={onManage}
            onAuthenticate={onAuthenticate}
            onReconnect={onReconnect}
            onDelete={onDelete}
            toolCount={toolCount}
            isToolsExpanded={isToolsExpanded}
            onToggleTools={handleToggleTools}
          />
        </div>

        {/* Tools Section (Only when expanded) */}
        {isToolsExpanded && (
          <ToolsSection
            onRefresh={onRefreshTools}
            onDisableAll={onDisableAllTools}
            onFold={handleFold}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
          />
        )}
      </div>

      {/* Tools List - Only render when expanded */}
      {isToolsExpanded && (
        <div className="animate-in fade-in slide-in-from-top-2 duration-300 p-2 border-t border-border-01">
          <ToolsList
            tools={filteredTools}
            searchQuery={searchQuery}
            onToolToggle={onToolToggle}
          />
        </div>
      )}
    </div>
  );
}
