"use client";

import React, { useState, useMemo, useEffect, useRef } from "react";
import SvgServer from "@/icons/server";
import ActionCard from "@/sections/actions/ActionCard";
import Actions from "@/sections/actions/Actions";
import ToolItem from "@/sections/actions/ToolItem";
import ToolsList from "@/sections/actions/ToolsList";
import { ActionStatus } from "@/lib/tools/types";
import { useServerTools } from "@/sections/actions/useServerTools";
import { MCPServerStatus, MCPServerWithStatus } from "@/lib/tools/types";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { KeyedMutator } from "swr";

export interface MCPActionCardProps {
  // Server identification
  serverId: number;
  server: MCPServerWithStatus;

  // Core content
  title: string;
  description: string;
  logo?: React.ReactNode;

  // Status
  status: ActionStatus;

  // Initial expanded state
  initialExpanded?: boolean;

  // Tool count (only for connected state)
  toolCount?: number;

  // Actions
  onDisconnect?: () => void;
  onManage?: () => void;
  onEdit?: () => void;
  onDelete?: () => void;
  onAuthenticate?: () => void; // For pending state
  onReconnect?: () => void; // For disconnected state
  onRename?: (serverId: number, newName: string) => Promise<void>; // For renaming

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
}

// Main Component
export default function MCPActionCard({
  serverId,
  server,
  title,
  description,
  logo,
  status,
  initialExpanded = false,
  toolCount,
  onDisconnect,
  onManage,
  onEdit,
  onDelete,
  onAuthenticate,
  onReconnect,
  onRename,
  onToolToggle,
  onRefreshTools,
  onDisableAllTools,
  className,
}: MCPActionCardProps) {
  const [isToolsExpanded, setIsToolsExpanded] = useState(initialExpanded);
  const [searchQuery, setSearchQuery] = useState("");
  const [showOnlyEnabled, setShowOnlyEnabled] = useState(false);

  // Update expanded state when initialExpanded changes
  const hasInitializedExpansion = useRef(false);

  // Apply initial expansion only once per component lifetime
  useEffect(() => {
    if (initialExpanded && !hasInitializedExpansion.current) {
      setIsToolsExpanded(true);
      hasInitializedExpansion.current = true;
    }
  }, [initialExpanded]);

  // Collapse tools when server becomes disconnected or awaiting auth
  useEffect(() => {
    if (
      server.status === MCPServerStatus.DISCONNECTED ||
      server.status === MCPServerStatus.AWAITING_AUTH
    ) {
      setIsToolsExpanded(false);
    }
  }, [server.status]);

  // Lazy load tools only when expanded
  const { tools, isLoading, mutate } = useServerTools({
    serverId,
    server,
    isExpanded: isToolsExpanded,
  });

  const isNotAuthenticated = status === ActionStatus.PENDING;

  // Filter tools based on search query and enabled status
  const filteredTools = useMemo(() => {
    if (!tools) return [];

    let filtered = tools;

    // Filter by enabled status if showOnlyEnabled is true
    if (showOnlyEnabled) {
      filtered = filtered.filter((tool) => tool.isEnabled);
    }

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (tool) =>
          tool.name.toLowerCase().includes(query) ||
          tool.description.toLowerCase().includes(query)
      );
    }

    return filtered;
  }, [tools, searchQuery, showOnlyEnabled]);

  const icon = !isNotAuthenticated ? (
    logo
  ) : (
    <SvgServer className="h-5 w-5 stroke-text-04" aria-hidden="true" />
  );

  const handleToggleTools = () => {
    setIsToolsExpanded((prev) => !prev);
    if (isToolsExpanded) {
      setSearchQuery("");
    }
  };

  const handleFold = () => {
    setIsToolsExpanded(false);
    setSearchQuery("");
    setShowOnlyEnabled(false);
  };

  const handleToggleShowOnlyEnabled = () => {
    setShowOnlyEnabled((prev) => !prev);
  };

  // Build the actions component
  const actionsComponent = (
    <Actions
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
  );

  const handleRename = async (newName: string) => {
    if (onRename) {
      await onRename(serverId, newName);
    }
  };

  return (
    <ActionCard
      title={title}
      description={description}
      icon={icon}
      status={status}
      actions={actionsComponent}
      onEdit={onEdit}
      onRename={handleRename}
      isExpanded={isToolsExpanded}
      onExpandedChange={setIsToolsExpanded}
      enableSearch={true}
      searchQuery={searchQuery}
      onSearchQueryChange={setSearchQuery}
      onRefresh={() => onRefreshTools?.(serverId, mutate)}
      onDisableAll={() => {
        const toolIds = tools.map((tool) => parseInt(tool.id));
        onDisableAllTools?.(serverId, toolIds, mutate);
      }}
      onFold={handleFold}
      className={className}
      ariaLabel={`${title} MCP server card`}
    >
      <ToolsList
        isFetching={server.status === MCPServerStatus.FETCHING_TOOLS}
        onRetry={() => mutate()}
        totalCount={tools.length}
        enabledCount={tools.filter((tool) => tool.isEnabled).length}
        showOnlyEnabled={showOnlyEnabled}
        onToggleShowOnlyEnabled={handleToggleShowOnlyEnabled}
        isEmpty={filteredTools.length === 0}
        searchQuery={searchQuery}
        emptyMessage="No tools available"
        emptySearchMessage="No tools found"
      >
        {filteredTools.map((tool) => (
          <ToolItem
            key={tool.id}
            name={tool.name}
            description={tool.description}
            icon={tool.icon}
            isAvailable={tool.isAvailable}
            isEnabled={tool.isEnabled}
            onToggle={(enabled) =>
              onToolToggle?.(serverId, tool.id, enabled, mutate)
            }
            variant="mcp"
          />
        ))}
      </ToolsList>
    </ActionCard>
  );
}
