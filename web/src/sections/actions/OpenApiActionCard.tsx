"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { PopupSpec } from "@/components/admin/connectors/Popup";
import ActionCard from "@/sections/actions/ActionCard";
import Actions from "@/sections/actions/Actions";
import ToolsList from "@/sections/actions/ToolsList";
import { useCreateModal } from "@/refresh-components/contexts/ModalContext";
import { ToolSnapshot, ActionStatus, MethodSpec } from "@/lib/tools/interfaces";
import ToolItem from "@/sections/actions/ToolItem";
import { extractMethodSpecsFromDefinition } from "@/lib/tools/openApiService";
import { updateToolStatus } from "@/lib/tools/mcpService";
import { SvgServer, SvgTrash } from "@opal/icons";
import Modal from "@/refresh-components/layouts/ConfirmationModalLayout";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@/lib/utils";

export interface OpenApiActionCardProps {
  tool: ToolSnapshot;
  onAuthenticate: (tool: ToolSnapshot) => void;
  onManage?: (tool: ToolSnapshot) => void;
  onDelete?: (tool: ToolSnapshot) => Promise<void> | void;
  onRename?: (toolId: number, newName: string) => Promise<void>;
  mutateOpenApiTools: () => Promise<unknown> | void;
  setPopup: (popup: PopupSpec | null) => void;
  onOpenDisconnectModal?: (tool: ToolSnapshot) => void;
}

export default function OpenApiActionCard({
  tool,
  onAuthenticate,
  onManage,
  onDelete,
  onRename,
  mutateOpenApiTools,
  setPopup,
  onOpenDisconnectModal,
}: OpenApiActionCardProps) {
  const [isToolsExpanded, setIsToolsExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const deleteModal = useCreateModal();

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

  const handleToggleTools = useCallback(() => {
    setIsToolsExpanded((prev) => !prev);
    if (isToolsExpanded) {
      setSearchQuery("");
    }
  }, [isToolsExpanded]);

  useEffect(() => {
    if (isDisconnected) {
      setIsToolsExpanded(false);
    }
  }, [isDisconnected]);

  const handleFold = () => {
    setIsToolsExpanded(false);
    setSearchQuery("");
  };

  // Build the actions component
  const actionsComponent = useMemo(
    () => (
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
        onDelete={onDelete ? () => deleteModal.toggle(true) : undefined}
      />
    ),
    [
      deleteModal,
      handleConnectionUpdate,
      handleToggleTools,
      isToolsExpanded,
      methodSpecs.length,
      onAuthenticate,
      onDelete,
      onManage,
      onOpenDisconnectModal,
      status,
      tool,
    ]
  );

  const handleRename = async (newName: string) => {
    if (onRename) {
      await onRename(tool.id, newName);
    }
  };

  return (
    <>
      <ActionCard
        title={tool.name}
        description={tool.description}
        icon={SvgServer}
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

      {deleteModal.isOpen && onDelete && (
        <Modal
          icon={({ className }) => (
            <SvgTrash className={cn(className, "stroke-action-danger-05")} />
          )}
          title="Delete OpenAPI action"
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              danger
              onClick={async () => {
                await onDelete(tool);
                deleteModal.toggle(false);
              }}
            >
              Delete
            </Button>
          }
        >
          <div className="flex flex-col gap-4">
            <Text as="p" text03>
              This will permanently delete the OpenAPI action <b>{tool.name}</b>{" "}
              and its configuration.
            </Text>
            <Text as="p" text03>
              Are you sure you want to delete this OpenAPI action?
            </Text>
          </div>
        </Modal>
      )}
    </>
  );
}
