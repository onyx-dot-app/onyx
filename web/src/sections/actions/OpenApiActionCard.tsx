"use client";

import React, { useCallback, useMemo, useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import SvgServer from "@/icons/server";
import ActionCard from "@/sections/actions/ActionCard";
import Actions from "@/sections/actions/Actions";
import ToolsList from "@/sections/actions/ToolsList";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { deleteCustomTool, updateCustomTool } from "@/lib/tools/openApiService";
import { ActionStatus, MethodSpec } from "@/lib/tools/types";
import ToolItem from "@/sections/actions/ToolItem";
import { extractMethodSpecsFromDefinition } from "@/lib/tools/openApiService";
import { updateToolStatus } from "@/lib/tools/mcpService";

export interface OpenApiActionCardProps {
  tool: ToolSnapshot;
  onAuthenticate: (tool: ToolSnapshot) => void;
  onManage?: (tool: ToolSnapshot) => void;
  onRename?: (toolId: number, newName: string) => Promise<void>;
  mutateOpenApiTools: () => Promise<unknown> | void;
  setPopup: (popup: PopupSpec | null) => void;
  onOpenDisconnectModal?: (tool: ToolSnapshot) => void;
}

export default function OpenApiActionCard({
  tool,
  onAuthenticate,
  onManage,
  onRename,
  mutateOpenApiTools,
  setPopup,
  onOpenDisconnectModal,
}: OpenApiActionCardProps) {
  const [isToolsExpanded, setIsToolsExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [updatingStatus, setUpdatingStatus] = useState(false);

  const methodSpecs = useMemo<MethodSpec[]>(() => {
    try {
      return extractMethodSpecsFromDefinition(tool.definition) ?? [];
    } catch (error) {
      console.error("Failed to parse OpenAPI definition", error);
      return [];
    }
  }, [tool.definition]);

  const filteredTools = useMemo(() => {
    if (!searchQuery.trim()) return methodSpecs;

    const query = searchQuery.toLowerCase();
    return methodSpecs.filter((method) => {
      const name = method.name?.toLowerCase() ?? "";
      const summary = method.summary?.toLowerCase() ?? "";
      return name.includes(query) || summary.includes(query);
    });
  }, [methodSpecs, searchQuery]);

  const hasCustomHeaders =
    Array.isArray(tool.custom_headers) && tool.custom_headers.length > 0;
  const hasAuthConfigured =
    Boolean(tool.oauth_config_id) ||
    Boolean(tool.passthrough_auth) ||
    hasCustomHeaders;
  const isDisconnected = !tool.enabled;

  // Compute generic ActionStatus for the OpenAPI tool
  const status = isDisconnected
    ? ActionStatus.DISCONNECTED
    : hasAuthConfigured
      ? ActionStatus.CONNECTED
      : ActionStatus.PENDING;

  const handleConnectionUpdate = useCallback(
    async (shouldEnable: boolean) => {
      if (updatingStatus || tool.enabled === shouldEnable) {
        return;
      }

      try {
        setUpdatingStatus(true);
        await updateToolStatus(tool.id, shouldEnable);
        await mutateOpenApiTools();
      } catch (error) {
        console.error("Failed to update OpenAPI tool status", error);
      } finally {
        setUpdatingStatus(false);
      }
    },
    [updatingStatus, mutateOpenApiTools, tool.enabled, tool.id]
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
  };

  // Build the actions component
  const actionsComponent = (
    <Actions
      status={status}
      serverName={tool.name}
      toolCount={methodSpecs.length}
      isToolsExpanded={isToolsExpanded}
      onToggleTools={methodSpecs.length ? handleToggleTools : undefined}
      onDisconnect={() => onOpenDisconnectModal?.(tool)}
      onManage={onManage ? () => onManage(tool) : undefined}
      onAuthenticate={() => {
        onAuthenticate(tool);
      }}
      onReconnect={() => handleConnectionUpdate(true)}
    />
  );

  const icon = (
    <SvgServer className="h-5 w-5 stroke-text-04" aria-hidden="true" />
  );

  const handleRename = async (newName: string) => {
    if (onRename) {
      await onRename(tool.id, newName);
    }
  };

  return (
    <ActionCard
      title={tool.name}
      description={tool.description}
      icon={icon}
      status={status}
      actions={actionsComponent}
      onRename={handleRename}
      isExpanded={isToolsExpanded}
      onExpandedChange={setIsToolsExpanded}
      enableSearch={true}
      searchQuery={searchQuery}
      onSearchQueryChange={setSearchQuery}
      onFold={handleFold}
      ariaLabel={`${tool.name} OpenAPI action card`}
    >
      <ToolsList
        isEmpty={filteredTools.length === 0}
        searchQuery={searchQuery}
        emptyMessage="No actions defined for this OpenAPI schema"
        emptySearchMessage="No actions match your search"
        className="gap-2"
      >
        {filteredTools.map((method) => (
          <ToolItem
            key={`${tool.id}-${method.method}-${method.path}-${method.name}`}
            name={method.name}
            description={method.summary || "No summary provided"}
            variant="openapi"
            openApiMetadata={{
              method: method.method,
              path: method.path,
            }}
          />
        ))}
      </ToolsList>
    </ActionCard>
  );
}
