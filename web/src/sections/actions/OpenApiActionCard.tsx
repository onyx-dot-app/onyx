"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import ActionCard from "@/sections/actions/ActionCard";
import Actions from "@/sections/actions/Actions";
import ToolsList from "@/sections/actions/ToolsList";
import { useCreateModal } from "@opal/components";
import { ToolSnapshot, ActionStatus, MethodSpec } from "@/lib/tools/types";
import ToolItem from "@/sections/actions/ToolItem";
import { extractMethodSpecsFromDefinition } from "@/lib/tools/utils";
import { updateToolStatus } from "@/lib/tools/svc";
import { can } from "@/lib/permissions/resource-actions";
import { SvgServer, SvgTrash } from "@opal/icons";
import { ConfirmationModalLayout as Modal } from "@opal/layouts";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { cn } from "@opal/utils";

export interface OpenApiActionCardProps {
  tool: ToolSnapshot;
  onAuthenticate: (tool: ToolSnapshot) => void;
  onManage?: (tool: ToolSnapshot) => void;
  onDelete?: (tool: ToolSnapshot) => Promise<void> | void;
  onRename?: (toolId: number, newName: string) => Promise<void>;
  mutateOpenApiTools: () => Promise<void> | void;
  onOpenDisconnectModal?: (tool: ToolSnapshot) => void;
}

export default function OpenApiActionCard({
  tool,
  onAuthenticate,
  onManage,
  onDelete,
  onRename,
  mutateOpenApiTools,
  onOpenDisconnectModal,
}: OpenApiActionCardProps) {
  const t = useTranslations("actions");
  const [isToolsExpanded, setIsToolsExpanded] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const [updatingStatus, setUpdatingStatus] = useState(false);
  const deleteModal = useCreateModal();

  const canEdit = can(tool, "edit");
  const canDelete = can(tool, "delete");
  const canToggle = can(tool, "toggle");
  // Authenticate manages the OAuth config (owner-or-admin) — gate on the server capability,
  // not canEdit, so a scoped non-owner isn't shown a 403 button.
  const canAuthenticate = can(tool, "authenticate");

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
        onDisconnect={
          canToggle ? () => onOpenDisconnectModal?.(tool) : undefined
        }
        onManage={canEdit && onManage ? () => onManage(tool) : undefined}
        onAuthenticate={
          canAuthenticate ? () => onAuthenticate(tool) : undefined
        }
        onReconnect={canToggle ? () => handleConnectionUpdate(true) : undefined}
        onDelete={
          canDelete && onDelete ? () => deleteModal.toggle(true) : undefined
        }
      />
    ),
    [
      canAuthenticate,
      canDelete,
      canEdit,
      canToggle,
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
        onRename={canEdit ? handleRename : undefined}
        isExpanded={isToolsExpanded}
        onExpandedChange={setIsToolsExpanded}
        enableSearch={true}
        searchQuery={searchQuery}
        onSearchQueryChange={setSearchQuery}
        onFold={handleFold}
        ariaLabel={t("openApiCard.card.ariaLabel", { name: tool.name })}
      >
        <ToolsList
          isEmpty={filteredTools.length === 0}
          searchQuery={searchQuery}
          emptyMessage={t("openApiCard.toolsList.emptyMessage")}
          emptySearchMessage={t("openApiCard.toolsList.emptySearchMessage")}
          className="gap-2"
        >
          {filteredTools.map((method) => (
            <ToolItem
              key={`${tool.id}-${method.method}-${method.path}-${method.name}`}
              name={method.name}
              description={method.summary || t("openApiCard.method.noSummary")}
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
          title={t("openApiCard.deleteModal.title")}
          onClose={() => deleteModal.toggle(false)}
          submit={
            <Button
              variant="danger"
              onClick={async () => {
                await onDelete(tool);
                deleteModal.toggle(false);
              }}
            >
              {t("openApiCard.deleteModal.submitButton.label")}
            </Button>
          }
        >
          <div className="flex flex-col gap-4">
            <Text as="p" text03>
              {t.rich("openApiCard.deleteModal.body.description", {
                name: tool.name,
                emphasis: (chunks) => <b>{chunks}</b>,
              })}
            </Text>
            <Text as="p" text03>
              {t("openApiCard.deleteModal.body.confirmation")}
            </Text>
          </div>
        </Modal>
      )}
    </>
  );
}
