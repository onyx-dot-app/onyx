"use client";

import { useTranslations } from "next-intl";
import { SelectCard } from "@opal/components";
import { SvgCheckCircle, SvgCodeFile, SvgXOctagon } from "@opal/icons";
import { getActionIcon } from "@/lib/tools/utils";
import { can } from "@/lib/permissions/resource-actions";
import { externalAppDisplayUrl } from "@/lib/plugins/externalAppDisplayUrl";
import type { InstalledPlugin } from "@/lib/plugins/types";
import PluginLifecycleMenu from "@/sections/plugins/PluginLifecycleMenu";
import { Content, ContentAction } from "@opal/layouts";
import { Hoverable } from "@opal/core";
import { MCPConnectionStatus } from "@/lib/mcp/types";
import { PLUGIN_KIND_TAGS } from "@/lib/plugins/constants";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import { useSettings } from "@/lib/settings/hooks";

/** Elements inside the card whose clicks are their own, not the card's. */
const NESTED_CONTROLS = "button, a, [role='menuitem'], [role='menu']";

interface PluginCardProps {
  plugin: InstalledPlugin;
  /** Opens the plugin's modal, with one-time parameters such as a tab. */
  onOpen: (params?: URLSearchParams) => void;
}

const HOVER_GROUP = "PluginCard";

/**
 * The plugin's sign-in state. Only an MCP server can need a sign-in; OpenAPI
 * tools and apps have no sign-in step, so they always read as connected.
 */
function PluginStatus({ plugin }: Pick<PluginCardProps, "plugin">) {
  const t = useTranslations("actions.memberPlugins");
  const needsSignIn =
    plugin.kind === "mcp" &&
    (plugin.server.connection_status === MCPConnectionStatus.NOT_CONNECTED ||
      plugin.server.connection_status === MCPConnectionStatus.REAUTH_REQUIRED);
  return (
    <div className="flex min-h-9 items-center p-2">
      <Content
        sizePreset="main-ui"
        variant="body"
        orientation="reverse"
        width="fit"
        icon={needsSignIn ? SvgXOctagon : SvgCheckCircle}
        title={t(needsSignIn ? "filters.needsSignIn" : "status.connected")}
        color={needsSignIn ? "danger" : "success"}
      />
    </div>
  );
}

/**
 * One installed plugin in the admin directory, in the same card pattern as
 * the Code Interpreter card: its sign-in status at the top right, and its
 * manage and delete buttons (delete on hover) below. The card opens the
 * plugin's detail page.
 */
export default function PluginCard({ plugin, onOpen }: PluginCardProps) {
  const t = useTranslations("actions.plugins");
  const settings = useSettings();
  const craftAvailable = settings.onyx_craft_available === true;
  const resource =
    plugin.kind === "mcp"
      ? plugin.server
      : plugin.kind === "openapi"
        ? plugin.tool
        : plugin.app;
  const description =
    plugin.kind === "mcp"
      ? plugin.server.description || plugin.server.server_url
      : plugin.kind === "openapi"
        ? plugin.tool.description
        : externalAppDisplayUrl(plugin.app.upstream_url_patterns);
  const icon =
    plugin.kind === "mcp"
      ? getActionIcon(plugin.server.server_url, plugin.server.name)
      : plugin.kind === "openapi"
        ? SvgCodeFile
        : getAppTypeLogo(plugin.app.app_type);
  const canManage =
    plugin.kind === "external-app" ||
    (plugin.kind === "mcp"
      ? can(plugin.server, "edit") || can(plugin.server, "authenticate")
      : can(plugin.tool, "edit") || can(plugin.tool, "authenticate"));

  return (
    <Hoverable.Root group={HOVER_GROUP}>
      <SelectCard
        state="filled"
        padding={2}
        rounding={4}
        aria-label={t(canManage ? "row.manage.label" : "row.view.label", {
          name: resource.name,
        })}
        onClick={(event) => {
          // A click on the card's own controls, or in the menu one opens (a
          // portal, so its clicks still bubble here), belongs to that control.
          if (
            event.target instanceof Element &&
            event.target.closest(NESTED_CONTROLS)
          )
            return;
          onOpen();
        }}
      >
        <ContentAction
          icon={icon}
          title={resource.name}
          tag={PLUGIN_KIND_TAGS[plugin.kind]}
          description={description}
          titleMaxLines={1}
          descriptionMaxLines={1}
          sizePreset="main-ui"
          variant="section"
          padding={2}
          rightChildren={
            <div className="flex flex-col items-end">
              <PluginStatus plugin={plugin} />
              <div className="px-1 pb-1">
                <PluginLifecycleMenu
                  plugin={plugin}
                  craftAvailable={craftAvailable}
                  deleteHoverGroup={HOVER_GROUP}
                  onOpen={onOpen}
                  size="md"
                />
              </div>
            </div>
          }
        />
      </SelectCard>
    </Hoverable.Root>
  );
}
