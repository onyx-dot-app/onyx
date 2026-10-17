"use client";

import { MCPConnectionStatus } from "@/lib/mcp/types";

import { useRef, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import {
  Button,
  Dropdown,
  Modal,
  Text,
  type DropdownMenuItem,
} from "@opal/components";
import { toast } from "@opal/layouts";
import { SvgPlug, SvgTrash, SvgUnplug } from "@opal/icons";
import { useDefaultAssistantConfiguration } from "@/lib/agents/hooks";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { deleteMCPServer, updateMCPServer } from "@/lib/mcp/svc";
import { MCPServerStatus } from "@/lib/mcp/types";
import { pluginDetailHref, withPluginSearchParams } from "@/lib/plugins/routes";
import { refreshMemberPluginCaches } from "@/lib/plugins/member";
import { can } from "@/lib/permissions/resource-actions";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import type { InstalledPlugin } from "@/lib/plugins/types";
import { useSettings } from "@/lib/settings/hooks";
import { SWR_KEYS } from "@/lib/swr-keys";
import { deleteCustomTool, updateToolStatus } from "@/lib/tools/svc";
import type { ToolSnapshot } from "@/lib/tools/types";
import ExternalAppLifecycleMenu from "@/sections/plugins/ExternalAppLifecycleMenu";

export interface PluginLifecycleMenuProps {
  plugin: InstalledPlugin;
  renderStatus?: (controls: {
    onOpen?: () => void;
    disabled: boolean;
    expanded: boolean;
  }) => ReactNode;
}

export default function PluginLifecycleMenu({
  plugin,
  renderStatus,
}: PluginLifecycleMenuProps) {
  const t = useTranslations("actions");
  const [activation, setActivation] = useState<
    "availability" | "delete" | null
  >(null);
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.FULL_ADMIN_PANEL_ACCESS
  );
  if (plugin.kind === "external-app")
    return isGlobalHolder ? (
      <ExternalAppLifecycleMenu app={plugin.app} renderStatus={renderStatus} />
    ) : (
      renderStatus?.({ disabled: false, expanded: false })
    );
  const resource = plugin.kind === "mcp" ? plugin.server : plugin.tool;
  const hasAvailability =
    plugin.kind === "openapi"
      ? can(plugin.tool, "toggle")
      : isGlobalHolder || can(plugin.server, "edit");
  if (activation)
    return (
      <ActivePluginLifecycleMenu
        plugin={plugin}
        initialAction={activation}
        renderStatus={renderStatus}
      />
    );
  return (
    <div className="flex items-center gap-2">
      {renderStatus?.({
        onOpen: hasAvailability
          ? () => setActivation("availability")
          : undefined,
        disabled: false,
        expanded: false,
      })}
      {hasAvailability ? (
        <Button
          size="sm"
          prominence="tertiary"
          icon={SvgPlug}
          aria-label={t("plugins.controls.disconnect")}
          tooltip={t("plugins.controls.disconnect")}
          aria-haspopup="menu"
          onClick={() => setActivation("availability")}
        />
      ) : (
        <span className="size-6 shrink-0" />
      )}
      {can(resource, "delete") ? (
        <Button
          size="sm"
          prominence="tertiary"
          icon={SvgTrash}
          aria-label={t("openApiCard.deleteModal.submitButton.label")}
          tooltip={t("openApiCard.deleteModal.submitButton.label")}
          onClick={() => setActivation("delete")}
        />
      ) : (
        <span className="size-6 shrink-0" />
      )}
    </div>
  );
}

function ActivePluginLifecycleMenu({
  plugin,
  initialAction,
  renderStatus,
}: {
  plugin: Exclude<InstalledPlugin, { kind: "external-app" }>;
  initialAction: "availability" | "delete";
  renderStatus?: PluginLifecycleMenuProps["renderStatus"];
}) {
  const t = useTranslations("actions");
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const settings = useSettings();
  const defaultChat = useDefaultAssistantConfiguration();
  const [open, setOpen] = useState(initialAction === "availability");
  const [confirmation, setConfirmation] = useState<
    "delete" | "disable-chat" | "disable-craft" | "disable-openapi" | null
  >(initialAction === "delete" ? "delete" : null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const writing = useRef(false);
  const resource = plugin.kind === "mcp" ? plugin.server : plugin.tool;
  const { data: tools, error: toolsError } = useSWR<ToolSnapshot[], Error>(
    plugin.kind === "mcp" &&
      (open || confirmation === "disable-chat") &&
      defaultChat.canEdit
      ? SWR_KEYS.adminMcpServerToolSnapshots(plugin.server.id)
      : null,
    errorHandlingFetcher,
    { revalidateOnFocus: false }
  );
  const busy = pending || defaultChat.isSaving;
  const selected =
    plugin.kind === "openapi"
      ? (defaultChat.data?.tool_ids.includes(plugin.tool.id) ??
        plugin.tool.default_chat_enabled === true)
      : tools && defaultChat.data
        ? tools.some((tool) => defaultChat.data?.tool_ids.includes(tool.id))
        : plugin.server.default_chat_enabled === true;

  async function runWrite(
    write: () => Promise<void>,
    fallback: string,
    deleted = false
  ) {
    if (writing.current || busy) return;
    writing.current = true;
    setPending(true);
    setError(null);
    try {
      await write();
      setConfirmation(null);
      toast.success(
        t(
          deleted
            ? plugin.kind === "mcp"
              ? "mcpPage.toasts.serverDeleted"
              : "openApiPage.toasts.toolDeleted"
            : "mcpDetail.availabilitySaved",
          { name: resource.name }
        )
      );
      const keys =
        plugin.kind === "mcp"
          ? [
              SWR_KEYS.adminMcpServers,
              ...(!deleted ? [SWR_KEYS.adminMcpServer(plugin.server.id)] : []),
              SWR_KEYS.mcpServers,
              SWR_KEYS.mcpServersCraft,
            ]
          : [SWR_KEYS.openApiTools];
      if (deleted && plugin.kind === "mcp") {
        await mutate(SWR_KEYS.adminMcpServer(plugin.server.id), undefined, {
          revalidate: false,
        });
        await mutate(
          SWR_KEYS.adminMcpServerToolSnapshots(plugin.server.id),
          undefined,
          { revalidate: false }
        );
      }
      await Promise.all(keys.map((key) => mutate(key))).catch(console.error);
      await refreshMemberPluginCaches(mutate).catch(console.error);
    } catch (cause) {
      const message =
        cause instanceof Error && cause.message ? cause.message : fallback;
      setError(message);
      toast.error(message);
    } finally {
      writing.current = false;
      setPending(false);
    }
  }

  const items: DropdownMenuItem[] = [];
  if (plugin.kind === "openapi" && can(plugin.tool, "toggle")) {
    const { tool } = plugin;
    const enabled = tool.enabled && (!defaultChat.canEdit || selected);
    items.push({
      kind: "action",
      id: "availability",
      icon: SvgUnplug,
      title: t(
        enabled ? "plugins.controls.disable" : "plugins.controls.enable"
      ),
      description: t("plugins.disableConfirmation.scope"),
      disabled:
        busy ||
        (defaultChat.canEdit && (!defaultChat.data || !!defaultChat.error)),
      onSelect: () => {
        if (enabled) {
          setOpen(false);
          setError(null);
          setConfirmation("disable-openapi");
          return;
        }
        void runWrite(async () => {
          if (!tool.enabled) await updateToolStatus(tool.id, true);
          if (defaultChat.canEdit)
            await defaultChat.updateTools([tool.id], true);
        }, t("addOpenApiModal.toasts.updateFailed"));
      },
    });
  }
  if (plugin.kind === "mcp") {
    const { server } = plugin;
    const authenticateToEnable =
      !selected &&
      (server.status === MCPServerStatus.AWAITING_AUTH ||
        server.connection_status === MCPConnectionStatus.NOT_CONNECTED ||
        server.connection_status === MCPConnectionStatus.REAUTH_REQUIRED ||
        (tools !== undefined && tools.length === 0));
    if (defaultChat.canEdit)
      items.push({
        kind: "action",
        id: "chat",
        icon: SvgUnplug,
        title: t(
          selected
            ? "plugins.controls.disableChat"
            : "plugins.controls.enableChat"
        ),
        description: selected
          ? t("plugins.disableConfirmation.scope")
          : undefined,
        disabled:
          busy ||
          (authenticateToEnable
            ? !can(server, "authenticate")
            : !defaultChat.data ||
              !!defaultChat.error ||
              !tools?.length ||
              !!toolsError),
        onSelect: () => {
          if (busy || !defaultChat.canEdit) return;
          if (authenticateToEnable) {
            if (!can(server, "authenticate")) return;
            setOpen(false);
            router.push(
              withPluginSearchParams(
                pluginDetailHref({ kind: "mcp", id: server.id }),
                { tab: "authentication", enable_chat: "true" }
              )
            );
            return;
          }
          if (
            !defaultChat.canEdit ||
            !tools?.length ||
            toolsError ||
            !defaultChat.data ||
            defaultChat.error
          )
            return;
          if (selected) {
            setOpen(false);
            setError(null);
            setConfirmation("disable-chat");
            return;
          }
          void runWrite(
            () =>
              defaultChat.updateTools(
                tools.map((tool) => tool.id),
                !selected
              ),
            t("addMcpModal.toasts.updateFailed")
          );
        },
      });
    if (settings.onyx_craft_available && can(server, "edit"))
      items.push({
        kind: "action",
        id: "craft",
        icon: SvgUnplug,
        title: t(
          server.available_in_craft
            ? "plugins.controls.disableCraft"
            : "plugins.controls.enableCraft"
        ),
        description: server.available_in_craft
          ? t("plugins.disableConfirmation.scope")
          : undefined,
        disabled: busy,
        onSelect: () => {
          if (busy) return;
          if (server.available_in_craft) {
            setOpen(false);
            setError(null);
            setConfirmation("disable-craft");
            return;
          }
          void runWrite(async () => {
            await updateMCPServer(server.id, {
              available_in_craft: true,
            });
          }, t("addMcpModal.toasts.updateFailed"));
        },
      });
  }

  async function deletePlugin() {
    if (!can(resource, "delete")) return;
    await runWrite(
      async () => {
        if (plugin.kind === "mcp") await deleteMCPServer(plugin.server.id);
        else {
          const response = await deleteCustomTool(plugin.tool.id);
          if (response.error || !response.data)
            throw new Error(
              response.error ?? t("openApiPage.toasts.deleteFailed")
            );
        }
      },
      t(
        plugin.kind === "mcp"
          ? "mcpPage.toasts.deleteFailed"
          : "openApiPage.toasts.deleteFailed"
      ),
      true
    );
  }

  async function disablePlugin() {
    if (plugin.kind === "openapi") {
      if (confirmation !== "disable-openapi" || !can(plugin.tool, "toggle"))
        return;
      await runWrite(async () => {
        await updateToolStatus(plugin.tool.id, false);
      }, t("addOpenApiModal.toasts.updateFailed"));
      return;
    }
    if (confirmation === "disable-chat") {
      if (
        !defaultChat.canEdit ||
        !defaultChat.data ||
        defaultChat.error ||
        !tools?.length ||
        toolsError
      )
        return;
      await runWrite(
        () =>
          defaultChat.updateTools(
            tools.map((tool) => tool.id),
            false
          ),
        t("addMcpModal.toasts.updateFailed")
      );
    } else if (confirmation === "disable-craft" && can(plugin.server, "edit")) {
      await runWrite(async () => {
        await updateMCPServer(plugin.server.id, { available_in_craft: false });
      }, t("addMcpModal.toasts.updateFailed"));
    }
  }

  const deleting = confirmation === "delete";
  const disablingChat = confirmation === "disable-chat";
  const disableScope = disablingChat
    ? "chat"
    : confirmation === "disable-craft"
      ? "craft"
      : "workspace";

  return (
    <>
      <div className="flex items-center gap-2">
        {renderStatus?.({
          onOpen: items.length ? () => setOpen(true) : undefined,
          disabled: busy,
          expanded: open,
        })}
        {items.length ? (
          <Dropdown open={open} onOpenChange={setOpen} align="end">
            <Dropdown.Trigger asChild>
              <Button
                size="sm"
                prominence="tertiary"
                icon={SvgPlug}
                aria-label={t("plugins.controls.disconnect")}
                tooltip={t("plugins.controls.disconnect")}
                disabled={busy}
              />
            </Dropdown.Trigger>
            <Dropdown.Data
              label={t("plugins.controls.disconnect")}
              items={items}
            />
          </Dropdown>
        ) : (
          <span className="size-6 shrink-0" />
        )}
        {can(resource, "delete") ? (
          <Button
            size="sm"
            prominence="tertiary"
            icon={SvgTrash}
            aria-label={t("openApiCard.deleteModal.submitButton.label")}
            tooltip={t("openApiCard.deleteModal.submitButton.label")}
            disabled={busy}
            onClick={() => {
              setOpen(false);
              setError(null);
              setConfirmation("delete");
            }}
          />
        ) : (
          <span className="size-6 shrink-0" />
        )}
      </div>
      <Modal
        open={confirmation !== null}
        onOpenChange={(next) => {
          if (!next && !busy) setConfirmation(null);
        }}
      >
        <Modal.Content width="sm" preventAccidentalClose={false}>
          <Modal.Header
            icon={deleting ? SvgTrash : SvgUnplug}
            title={
              deleting
                ? t(
                    plugin.kind === "mcp"
                      ? "mcpCard.deleteModal.title"
                      : "openApiCard.deleteModal.title"
                  )
                : t(`plugins.disableConfirmation.${disableScope}Title`, {
                    name: resource.name,
                  })
            }
            onClose={() => {
              if (!busy) setConfirmation(null);
            }}
          />
          <Modal.Body twoTone={false}>
            <Text as="p" color="text-03">
              {!deleting
                ? t(`plugins.disableConfirmation.${disableScope}Description`, {
                    name: resource.name,
                  })
                : plugin.kind === "mcp"
                  ? t.markup("mcpCard.deleteModal.body.description", {
                      title: resource.name,
                      emphasis: (chunks) => chunks,
                    })
                  : t("plugins.openapi.deleteDescription")}
            </Text>
            {deleting && plugin.kind === "mcp" && (
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
              disabled={busy}
              onClick={() => setConfirmation(null)}
            >
              {t("addMcpModal.cancelButton.label")}
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => void (deleting ? deletePlugin() : disablePlugin())}
            >
              {t(
                deleting
                  ? "openApiCard.deleteModal.submitButton.label"
                  : confirmation === "disable-openapi"
                    ? "plugins.controls.disable"
                    : disablingChat
                      ? "plugins.controls.disableChat"
                      : "plugins.controls.disableCraft"
              )}
            </Button>
          </Modal.Footer>
        </Modal.Content>
      </Modal>
    </>
  );
}
