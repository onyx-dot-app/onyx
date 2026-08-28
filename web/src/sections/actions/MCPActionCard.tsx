"use client";

import React, {
  useState,
  useMemo,
  useEffect,
  useRef,
  useCallback,
} from "react";
import { useTranslations } from "next-intl";
import ActionCard from "@/sections/actions/ActionCard";
import Actions from "@/sections/actions/Actions";
import ToolItem from "@/sections/actions/ToolItem";
import ToolsList from "@/sections/actions/ToolsList";
import { useCreateModal } from "@opal/components";
import {
  ActionStatus,
  ToolSnapshot,
  MCPServerStatus,
  MCPServer,
} from "@/lib/tools/types";
import useServerTools from "@/hooks/useServerTools";
import { can } from "@/lib/permissions/resource-actions";
import { KeyedMutator } from "swr";
import type { IconProps } from "@opal/types";
import {
  SvgRefreshCw,
  SvgServer,
  SvgTrash,
  SvgSimpleLoader,
} from "@opal/icons";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { timeAgo } from "@opal/time";
import { cn } from "@opal/utils";
import { ConfirmationModalLayout as Modal } from "@opal/layouts";

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
  const t = useTranslations("actions");
  const [isToolsExpanded, setIsToolsExpanded] = useState(initialExpanded);
  const [searchQuery, setSearchQuery] = useState("");
  const [showOnlyEnabled, setShowOnlyEnabled] = useState(false);
  const [isToolsRefreshing, setIsToolsRefreshing] = useState(false);
  const deleteModal = useCreateModal();

  const canEdit = can(server, "edit");
  const canDelete = can(server, "delete");
  const canAuthenticate = can(server, "authenticate");
  const canManageStatus = can(server, "manage_status");

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
        onDisconnect={canManageStatus ? onDisconnect : undefined}
        onManage={canEdit ? onManage : undefined}
        onAuthenticate={canAuthenticate ? onAuthenticate : undefined}
        onReconnect={canManageStatus ? onReconnect : undefined}
        onDelete={
          canDelete && onDelete ? () => deleteModal.toggle(true) : undefined
        }
        toolCount={toolCount}
        isToolsExpanded={isToolsExpanded}
        onToggleTools={handleToggleTools}
      />
    ),
    [
      canAuthenticate,
      canDelete,
      canEdit,
      canManageStatus,
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
        {canManageStatus && (
          <Button
            icon={isToolsRefreshing ? SvgSimpleLoader : SvgRefreshCw}
            prominence="internal"
            onClick={handleRefreshTools}
            tooltip={t("mcpCard.refreshToolsButton.tooltip")}
            aria-label={t("mcpCard.refreshToolsButton.ariaLabel")}
          />
        )}
        {lastRefreshedText && (
          <Text as="p" text03 mainUiBody className="whitespace-nowrap">
            {t("mcpCard.lastRefreshed.label", { time: lastRefreshedText })}
          </Text>
        )}
      </div>
    );
  }, [
    canManageStatus,
    server.last_refreshed_at,
    serverId,
    mutate,
    onRefreshTools,
    isToolsRefreshing,
    t,
  ]);

  return (
    <>
      <ActionCard
        title={title}
        description={description}
        icon={icon}
        status={status}
        actions={actionsComponent}
        onEdit={canEdit ? onEdit : undefined}
        onRename={canEdit ? handleRename : undefined}
        isExpanded={isToolsExpanded}
        onExpandedChange={setIsToolsExpanded}
        enableSearch={true}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        onFold={handleFold}
        className={className}
        ariaLabel={t("mcpCard.card.ariaLabel", { title })}
      >
        <ToolsList
          isFetching={
            server.status === MCPServerStatus.FETCHING_TOOLS || isLoading
          }
          totalCount={tools.length}
          enabledCount={tools.filter((tool) => tool.isEnabled).length}
          showOnlyEnabled={showOnlyEnabled}
          onToggleShowOnlyEnabled={handleToggleShowOnlyEnabled}
          onUpdateToolsStatus={
            // Bulk toggles all tools; the status route 403s the whole batch unless every
            // tool is manageable, so only offer it when the user can toggle each one.
            tools.length > 0 && tools.every((tool) => can(tool, "toggle"))
              ? (enabled) => {
                  const toolIds = tools.map((tool) => parseInt(tool.id));
                  onUpdateToolsStatus?.(serverId, toolIds, enabled, mutate);
                }
              : undefined
          }
          isEmpty={filteredTools.length === 0}
          searchQuery={searchQuery}
          emptyMessage={t("toolsList.empty.message")}
          emptySearchMessage={t("toolsList.empty.searchMessage")}
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
              canToggle={can(tool, "toggle")}
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
          title={t("mcpCard.deleteModal.title")}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              variant="danger"
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
              {t("mcpCard.deleteModal.submitButton.label")}
            </Button>
          }
        >
          <div className="flex flex-col gap-4">
            <Text as="p" text03>
              {t.rich("mcpCard.deleteModal.body.description", {
                title,
                emphasis: (chunks) => <b>{chunks}</b>,
              })}
            </Text>
            <Text as="p" text03>
              {t("mcpCard.deleteModal.body.confirmation")}
            </Text>
          </div>
        </Modal>
      )}
    </>
  );
}
