"use client";

import React, { useCallback, useMemo, useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import { ConfirmEntityModal } from "@/components/modals/ConfirmEntityModal";
import SvgServer from "@/icons/server";
import ActionCardHeader from "@/sections/actions/ActionCardHeader";
import Actions from "@/sections/actions/Actions";
import ToolsSection from "@/sections/actions/ToolsSection";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { deleteCustomTool } from "@/lib/tools/openApiService";
import { MCPActionStatus, MethodSpec } from "@/lib/tools/types";
import { cn } from "@/lib/utils";
import ToolItem from "@/sections/actions/ToolItem";
import Text from "@/refresh-components/texts/Text";
import { extractMethodSpecsFromDefinition } from "@/lib/tools/openApiService";
import { updateToolStatus } from "@/lib/tools/mcpService";

export interface OpenApiActionCardProps {
  tool: ToolSnapshot;
  onAuthenticate: (tool: ToolSnapshot) => void;
  onManage?: (tool: ToolSnapshot) => void;
  mutateOpenApiTools: () => Promise<unknown> | void;
  setPopup: (popup: PopupSpec | null) => void;
  onOpenDisconnectModal?: (tool: ToolSnapshot) => void;
}

export default function OpenApiActionCard({
  tool,
  onAuthenticate,
  onManage,
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
  const status = isDisconnected
    ? MCPActionStatus.DISCONNECTED
    : hasAuthConfigured
      ? MCPActionStatus.CONNECTED
      : MCPActionStatus.PENDING;

  const backgroundColor =
    status === MCPActionStatus.CONNECTED
      ? "bg-background-tint-00"
      : status === MCPActionStatus.DISCONNECTED
        ? "bg-background-neutral-02"
        : "";

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

  return (
    <div
      className={cn(
        "w-full border border-border-01 rounded-16",
        backgroundColor
      )}
    >
      <div className="flex flex-col w-full">
        <div className="flex items-start justify-between pb-2 pl-3 pt-3 pr-2 w-full">
          <ActionCardHeader
            title={tool.name}
            description={tool.description}
            icon={
              <SvgServer
                className="h-5 w-5 stroke-text-04"
                aria-hidden="true"
              />
            }
            status={status}
          />

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
        </div>

        {isToolsExpanded && (
          <ToolsSection
            onFold={handleFold}
            searchQuery={searchQuery}
            onSearchQueryChange={setSearchQuery}
          />
        )}
      </div>

      {isToolsExpanded && (
        <div className="animate-in fade-in slide-in-from-top-2 duration-300 p-2 border-t border-border-01 flex flex-col gap-2">
          {filteredTools.length > 0 ? (
            filteredTools.map((method) => (
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
            ))
          ) : (
            <div className="flex items-center justify-center w-full py-6">
              <Text text03 secondaryBody>
                {searchQuery
                  ? "No actions match your search"
                  : "No actions defined for this OpenAPI schema"}
              </Text>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
