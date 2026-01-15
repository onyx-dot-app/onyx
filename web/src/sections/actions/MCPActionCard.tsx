"use client";

import React, {
  useState,
  useMemo,
  useEffect,
  useRef,
  useCallback,
} from "react";
import ActionCard from "@/sections/actions/ActionCard";
import Actions from "@/sections/actions/Actions";
import ToolItem from "@/sections/actions/ToolItem";
import ToolsList from "@/sections/actions/ToolsList";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import {
  ActionStatus,
  ToolSnapshot,
  MCPServerStatus,
  MCPServer,
} from "@/lib/tools/interfaces";
import useServerTools from "@/hooks/useServerTools";
import { KeyedMutator } from "swr";
import type { IconProps } from "@opal/types";
import { SvgRefreshCw, SvgServer, SvgTrash } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { timeAgo } from "@/lib/time";
import { cn } from "@/lib/utils";
import Modal from "@/refresh-components/layouts/ConfirmationModalLayout";

export interface MCPActionCardProps {
  // Server identification
  serverId: number;
  server: MCPServer;

  // Core content
  title: string;
  description: string;
  logo?: React.FunctionComponent<IconProps>;

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
  onDelete?: () => Promise<void> | void;
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
  onUpdateToolsStatus?: (
    serverId: number,
    toolIds: number[],
    enabled: boolean,
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
  onUpdateToolsStatus,
  className,
}: MCPActionCardProps) {
  const [isToolsExpanded, setIsToolsExpanded] = useState(initialExpanded);
  const [searchQuery, setSearchQuery] = useState("");
  const [showOnlyEnabled, setShowOnlyEnabled] = useState(false);
  const [isToolsRefreshing, setIsToolsRefreshing] = useState(false);
  const deleteModal = useCreateModal();

  // Update expanded state when initialExpanded changes
  const hasInitializedExpansion = useRef(false);
  const previousStatus = useRef<MCPServerStatus>(server.status);
  const hasRetriedTools = useRef(false);

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
  const { tools, isLoading, mutate } = useServerTools(server, isToolsExpanded);

  // Retry tools fetch when server transitions from FETCHING_TOOLS to CONNECTED
  useEffect(() => {
    const statusChanged =
      previousStatus.current === MCPServerStatus.FETCHING_TOOLS &&
      server.status === MCPServerStatus.CONNECTED;

    if (statusChanged && tools.length === 0 && !hasRetriedTools.current) {
      console.log(
        "Server status changed to CONNECTED with empty tools, retrying fetch"
      );
      hasRetriedTools.current = true;
      mutate();
    }

    // Update previous status
    previousStatus.current = server.status;
  }, [server.status, tools.length, mutate]);

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

  const icon = isNotAuthenticated ? SvgServer : logo;

  const handleToggleTools = useCallback(() => {
    setIsToolsExpanded((prev) => !prev);
    if (isToolsExpanded) {
      setSearchQuery("");
    }
  }, [isToolsExpanded]);

  const handleFold = () => {
    setIsToolsExpanded(false);
    setSearchQuery("");
    setShowOnlyEnabled(false);
  };

  const handleToggleShowOnlyEnabled = () => {
    setShowOnlyEnabled((prev) => !prev);
  };

  // Build the actions component
  const actionsComponent = useMemo(
    () => (
      <Actions
        status={status}
        serverName={title}
        onDisconnect={onDisconnect}
        onManage={onManage}
        onAuthenticate={onAuthenticate}
        onReconnect={onReconnect}
        onDelete={onDelete ? () => deleteModal.toggle(true) : undefined}
        toolCount={toolCount}
        isToolsExpanded={isToolsExpanded}
        onToggleTools={handleToggleTools}
      />
    ),
    [
      deleteModal,
      handleToggleTools,
      isToolsExpanded,
      onAuthenticate,
      onDelete,
      onDisconnect,
      onManage,
      onReconnect,
      status,
      title,
      toolCount,
    ]
  );

  const handleRename = async (newName: string) => {
    if (onRename) {
      await onRename(serverId, newName);
    }
  };

  const handleRefreshTools = () => {
    setIsToolsRefreshing(true);
    onRefreshTools?.(serverId, mutate);
    setTimeout(() => {
      setIsToolsRefreshing(false);
    }, 1000);
  };

  // Left action for ToolsList footer
  const leftAction = useMemo(() => {
    const lastRefreshedText = timeAgo(server.last_refreshed_at);

    return (
      <div className="flex items-center gap-2">
        <IconButton
          icon={SvgRefreshCw}
          internal
          onClick={handleRefreshTools}
          tooltip="Refresh tools"
          aria-label="Refresh tools"
          className={cn(isToolsRefreshing && "animate-spin")}
        />
        {lastRefreshedText && (
          <Text as="p" text03 mainUiBody className="whitespace-nowrap">
            Tools last refreshed {lastRefreshedText}
          </Text>
        )}
      </div>
    );
  }, [
    server.last_refreshed_at,
    serverId,
    mutate,
    onRefreshTools,
    isToolsRefreshing,
  ]);

  return (
    <>
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
        onFold={handleFold}
        className={className}
        ariaLabel={`${title} MCP server card`}
      >
        <ToolsList
          isFetching={
            server.status === MCPServerStatus.FETCHING_TOOLS || isLoading
          }
          totalCount={tools.length}
          enabledCount={tools.filter((tool) => tool.isEnabled).length}
          showOnlyEnabled={showOnlyEnabled}
          onToggleShowOnlyEnabled={handleToggleShowOnlyEnabled}
          onUpdateToolsStatus={(enabled) => {
            const toolIds = tools.map((tool) => parseInt(tool.id));
            onUpdateToolsStatus?.(serverId, toolIds, enabled, mutate);
          }}
          isEmpty={filteredTools.length === 0}
          searchQuery={searchQuery}
          emptyMessage="No tools available"
          emptySearchMessage="No tools found"
          leftAction={leftAction}
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

      {deleteModal.isOpen && (
        <Modal
          icon={({ className }) => (
            <SvgTrash className={cn(className, "stroke-action-danger-05")} />
          )}
          title="Delete MCP server"
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              danger
              onClick={async () => {
                if (!onDelete) return;
                try {
                  await onDelete();
                  deleteModal.toggle(false);
                } catch (error) {
                  // Keep modal open if deletion fails; caller should surface error feedback.
                  console.error("Failed to delete MCP server", error);
                }
              }}
            >
              Delete
            </Button>
          }
        >
          <div className="flex flex-col gap-4">
            <Text as="p" text03>
              All tools connected to <b>{title}</b> will be removed. Deletion is
              irreversible.
            </Text>
            <Text as="p" text03>
              Are you sure you want to delete this MCP server?
            </Text>
          </div>
        </Modal>
      )}
    </>
  );
}
