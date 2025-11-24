"use client";

import React, { useState, useMemo } from "react";
import SvgServer from "@/icons/server";
import ActionCardHeader from "./ActionCardHeader";
import MCPActions from "./MCPActions";
import ToolsSection from "./ToolsSection";
import ToolsList from "./ToolsList";
import { cn } from "@/lib/utils";
import type { MCPActionStatus } from "./types";
import { useServerTools } from "@/app/admin/mcp-actions/useServerTools";
import { MCPServerWithStatus } from "@/app/admin/mcp-actions/types";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { KeyedMutator } from "swr";

export interface ActionCardProps {
  // Server identification
  serverId: number;
  server: MCPServerWithStatus;

  // Core content
  title: string;
  description: string;
  logo?: React.ReactNode;

  // Status
  status?: MCPActionStatus;

  // Tool count (only for connected state)
  toolCount?: number;

  // Actions
  onDisconnect?: () => void;
  onManage?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onAuthenticate?: () => void; // For pending state
  onReconnect?: () => void; // For disconnected state

  // Tool-related actions (now includes SWR mutate function for optimistic updates)
  onToolToggle?: (
    serverId: number,
    toolId: string,
    enabled: boolean,
    mutate: KeyedMutator<ToolSnapshot[]>
  ) => void;
  onRefreshTools?: (
    serverId: number,
    mutate: KeyedMutator<ToolSnapshot[]>
  ) => void;
  onDisableAllTools?: (
    serverId: number,
    toolIds: number[],
    mutate: KeyedMutator<ToolSnapshot[]>
  ) => void;

  // Optional styling
  className?: string;

  // Whether the tools are still being fetched
  isInitialToolsFetching?: boolean;
}

// Main Component
export default function ActionCard({
  serverId,
  server,
  title,
  description,
  logo,
  status = "connected",
  toolCount,
  onDisconnect,
  onManage,
  onEdit,
  onDelete,
  onAuthenticate,
  onReconnect,
  onToolToggle,
  onRefreshTools,
  onDisableAllTools,
  isInitialToolsFetching,
  className,
}: ActionCardProps) {
  const [isToolsExpanded, setIsToolsExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  // Lazy load tools only when expanded
  const { tools, isLoading, mutate } = useServerTools({
    serverId,
    server,
    isExpanded: isToolsExpanded,
  });

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
            onRefresh={() => onRefreshTools?.(serverId, mutate)}
            onDisableAll={() => {
              const toolIds = tools.map((tool) => parseInt(tool.id));
              onDisableAllTools?.(serverId, toolIds, mutate);
            }}
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
            onToolToggle={(toolId, enabled) =>
              onToolToggle?.(serverId, toolId, enabled, mutate)
            }
            isInitialToolsFetching={isInitialToolsFetching || isLoading}
          />
        </div>
      )}
    </div>
  );
}
