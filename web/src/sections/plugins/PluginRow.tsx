"use client";

import { useTranslations } from "next-intl";
import Link from "next/link";
import { useId } from "react";
import { Button, SelectCard, Text, Tooltip } from "@opal/components";
import { SvgFileBraces } from "@opal/icons";
import type { IconProps } from "@opal/types";
import { cn } from "@opal/utils";
import { getActionIcon } from "@/lib/tools/utils";
import { can } from "@/lib/permissions/resource-actions";
import { pluginDetailHref } from "@/lib/plugins/routes";
import { externalAppDisplayUrl } from "@/lib/plugins/externalAppDisplayUrl";
import type { InstalledPlugin } from "@/lib/plugins/types";
import PluginLifecycleMenu from "@/sections/plugins/PluginLifecycleMenu";
import PluginRowLayout from "@/sections/plugins/PluginRowLayout";
import { getAppTypeLogo } from "@/app/craft/v1/apps/registry";
import { useSettings } from "@/lib/settings/hooks";

interface PluginRowProps {
  plugin: InstalledPlugin;
}

function PluginAvailability({
  plugin,
  onOpen,
  disabled,
  expanded,
}: PluginRowProps & {
  onOpen?: () => void;
  disabled: boolean;
  expanded: boolean;
}) {
  const t = useTranslations("actions.plugins.availability");
  const craftDescriptionId = useId();
  const settings = useSettings();
  const craftAvailable = settings.onyx_craft_available === true;
  const enabled =
    plugin.kind === "external-app"
      ? plugin.app.enabled
      : plugin.kind === "openapi"
        ? plugin.tool.enabled
        : plugin.server.default_chat_enabled;
  const label =
    plugin.kind === "external-app"
      ? t(enabled ? "craftEnabled" : "craftDisabled")
      : plugin.kind === "openapi"
        ? t(enabled ? "enabled" : "disabled")
        : t(
            enabled == null
              ? "chatUnknown"
              : enabled
                ? "chatEnabled"
                : "chatDisabled"
          );
  const craftLabel =
    craftAvailable &&
    plugin.kind === "mcp" &&
    plugin.server.available_in_craft !== undefined
      ? t(plugin.server.available_in_craft ? "craftEnabled" : "craftDisabled")
      : null;
  function StatusIcon({ className }: IconProps) {
    const chatColor =
      enabled == null
        ? "bg-text-02"
        : enabled
          ? "bg-status-success-05"
          : "bg-text-03";
    if (plugin.kind !== "mcp" || !craftAvailable)
      return (
        <span
          aria-hidden
          className={cn("block size-3 rounded-full", chatColor, className)}
        />
      );
    const craftColor =
      plugin.server.available_in_craft == null
        ? "bg-text-02"
        : plugin.server.available_in_craft
          ? "bg-status-success-05"
          : "bg-text-03";
    return (
      <span
        aria-hidden
        className={cn(
          "relative block size-3 overflow-hidden rounded-full",
          className
        )}
      >
        <span
          className={cn(
            "absolute inset-0 [clip-path:polygon(0_0,100%_0,0_100%)]",
            chatColor
          )}
        />
        <span
          className={cn(
            "absolute inset-0 [clip-path:polygon(100%_0,100%_100%,0_100%)]",
            craftColor
          )}
        />
        <span className="absolute inset-x-0 top-1/2 h-px -rotate-45 bg-background-neutral-00" />
      </span>
    );
  }
  return (
    <>
      <Tooltip
        side="top"
        tone="neutral"
        sideOffset={6}
        delayDuration={250}
        tooltip={
          <div className="grid grid-cols-[auto_auto] items-center gap-x-6 gap-y-1.5">
            <Text font="secondary-body" color="text-03">
              {t(plugin.kind === "external-app" ? "craft" : "mainChat")}
            </Text>
            <Text font="secondary-body" color="text-04">
              {t(enabled == null ? "unknown" : enabled ? "on" : "off")}
            </Text>
            {craftLabel && (
              <>
                <Text font="secondary-body" color="text-03">
                  {t("craft")}
                </Text>
                <Text font="secondary-body" color="text-04">
                  {t(
                    plugin.kind === "mcp" && plugin.server.available_in_craft
                      ? "on"
                      : "off"
                  )}
                </Text>
              </>
            )}
          </div>
        }
      >
        <Button
          size="sm"
          prominence="tertiary"
          icon={StatusIcon}
          aria-label={label}
          aria-describedby={craftLabel ? craftDescriptionId : undefined}
          onClick={onOpen}
          disabled={disabled}
          aria-haspopup={onOpen ? "menu" : undefined}
          aria-expanded={onOpen ? expanded : undefined}
        />
      </Tooltip>
      {craftLabel && (
        <span id={craftDescriptionId} className="sr-only">
          <Text>{craftLabel}</Text>
        </span>
      )}
    </>
  );
}

export function PluginRow({ plugin }: PluginRowProps) {
  const t = useTranslations("actions.plugins");
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
        ? SvgFileBraces
        : getAppTypeLogo(plugin.app.app_type);
  const canManage =
    plugin.kind === "external-app" ||
    (plugin.kind === "mcp"
      ? can(plugin.server, "edit") || can(plugin.server, "authenticate")
      : can(plugin.tool, "edit") || can(plugin.tool, "authenticate"));

  return (
    <div className="relative min-w-0" role="group" aria-label={resource.name}>
      <SelectCard border="none" padding={0}>
        <div className="flex min-w-0 items-center gap-2 pe-3">
          <Link
            href={pluginDetailHref({ kind: plugin.kind, id: resource.id })}
            aria-label={t(canManage ? "row.manage.label" : "row.view.label", {
              name: resource.name,
            })}
            className="block min-w-0 flex-1 rounded-12 focus-visible:outline focus-visible:outline-2"
          >
            <PluginRowLayout
              icon={icon}
              title={resource.name}
              description={description}
              action={
                <Text font="secondary-body" color="text-03">
                  {t(`kind.${plugin.kind}`)}
                </Text>
              }
            />
          </Link>
          <PluginLifecycleMenu
            plugin={plugin}
            renderStatus={(controls) => (
              <PluginAvailability plugin={plugin} {...controls} />
            )}
          />
        </div>
      </SelectCard>
    </div>
  );
}
