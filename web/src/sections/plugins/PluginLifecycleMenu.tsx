"use client";

import { useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useSWRConfig } from "swr";
import { Button, Modal, Text } from "@opal/components";
import { toast } from "@opal/layouts";
import { SvgTrash } from "@opal/icons";
import { deleteMCPServer } from "@/lib/mcp/svc";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import { can } from "@/lib/permissions/resource-actions";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import type { InstalledPlugin } from "@/lib/plugins/types";
import { SWR_KEYS } from "@/lib/swr-keys";
import { deleteCustomTool } from "@/lib/tools/svc";
import ExternalAppLifecycleMenu from "@/sections/plugins/ExternalAppLifecycleMenu";

export interface PluginLifecycleMenuProps {
  plugin: InstalledPlugin;
  renderStatus?: (controls: { disabled: boolean }) => ReactNode;
}

export default function PluginLifecycleMenu({
  plugin,
  renderStatus,
}: PluginLifecycleMenuProps) {
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  if (plugin.kind === "external-app")
    return isGlobalHolder ? (
      <ExternalAppLifecycleMenu app={plugin.app} renderStatus={renderStatus} />
    ) : (
      renderStatus?.({ disabled: false })
    );
  return <PluginDeleteControl plugin={plugin} renderStatus={renderStatus} />;
}

function PluginDeleteControl({
  plugin,
  renderStatus,
}: {
  plugin: Exclude<InstalledPlugin, { kind: "external-app" }>;
  renderStatus?: PluginLifecycleMenuProps["renderStatus"];
}) {
  const t = useTranslations("actions");
  const { mutate } = useSWRConfig();
  const [open, setOpen] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const writing = useRef(false);
  const resource = plugin.kind === "mcp" ? plugin.server : plugin.tool;
  async function remove() {
    if (writing.current || !can(resource, "delete")) return;
    writing.current = true;
    setPending(true);
    setError(null);
    try {
      if (plugin.kind === "mcp") await deleteMCPServer(plugin.server.id);
      else {
        const response = await deleteCustomTool(plugin.tool.id);
        if (response.error || !response.data)
          throw new Error(
            response.error ?? t("openApiPage.toasts.deleteFailed")
          );
      }
      setOpen(false);
      toast.success(
        t(
          plugin.kind === "mcp"
            ? "mcpPage.toasts.serverDeleted"
            : "openApiPage.toasts.toolDeleted",
          { name: resource.name }
        )
      );
      if (plugin.kind === "mcp") {
        await mutate(SWR_KEYS.adminMcpServer(plugin.server.id), undefined, {
          revalidate: false,
        });
        await mutate(
          SWR_KEYS.adminMcpServerToolSnapshots(plugin.server.id),
          undefined,
          { revalidate: false }
        );
      }
      await mutate(
        plugin.kind === "mcp" ? SWR_KEYS.adminMcpServers : SWR_KEYS.openApiTools
      ).catch(console.error);
      await refreshMemberPluginCaches(mutate).catch(console.error);
    } catch (cause) {
      const message =
        cause instanceof Error
          ? cause.message
          : t(
              plugin.kind === "mcp"
                ? "mcpPage.toasts.deleteFailed"
                : "openApiPage.toasts.deleteFailed"
            );
      setError(message);
      toast.error(message);
    } finally {
      writing.current = false;
      setPending(false);
    }
  }
  return (
    <>
      <div className="flex items-center gap-2">
        {renderStatus?.({ disabled: pending })}
        {can(resource, "delete") ? (
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgTrash}
            aria-label={t("openApiCard.deleteModal.submitButton.label")}
            tooltip={t("openApiCard.deleteModal.submitButton.label")}
            disabled={pending}
            onClick={() => {
              setError(null);
              setOpen(true);
            }}
          />
        ) : (
          <span className="size-6 shrink-0" />
        )}
      </div>
      <Modal
        open={open}
        onOpenChange={(next) => {
          if (!pending) setOpen(next);
        }}
      >
        <Modal.Content width="sm" preventAccidentalClose={false}>
          <Modal.Header
            icon={SvgTrash}
            title={t(
              plugin.kind === "mcp"
                ? "mcpCard.deleteModal.title"
                : "openApiCard.deleteModal.title"
            )}
            onClose={() => {
              if (!pending) setOpen(false);
            }}
          />
          <Modal.Body twoTone={false}>
            <Text as="p" color="text-03">
              {plugin.kind === "mcp"
                ? t.markup("mcpCard.deleteModal.body.description", {
                    title: resource.name,
                    emphasis: (chunks) => chunks,
                  })
                : t("plugins.openapi.deleteDescription")}
            </Text>
            {plugin.kind === "mcp" && (
              <Text as="p" color="text-03">
                {t("mcpCard.deleteModal.body.confirmation")}
              </Text>
            )}
            {error && (
              <Text as="p" color="status-error-05">
                {error}
              </Text>
            )}
          </Modal.Body>
          <Modal.Footer>
            <Button
              prominence="secondary"
              disabled={pending}
              onClick={() => setOpen(false)}
            >
              {t("addMcpModal.cancelButton.label")}
            </Button>
            <Button
              variant="danger"
              disabled={pending}
              onClick={() => void remove()}
            >
              {t("openApiCard.deleteModal.submitButton.label")}
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
