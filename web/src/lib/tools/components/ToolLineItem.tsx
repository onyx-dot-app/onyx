"use client";

import { Fragment, useMemo } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import type { Route } from "next";
import { Button, LineItemButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgChevronRight, SvgKey, SvgSettings, SvgSlash } from "@opal/icons";
import { getIconForAction } from "@/app/app/services/actionUtils";
import useCCPairs from "@/hooks/useCCPairs";
import { Section } from "@/layouts/general-layouts";
import {
  useToolOAuthStatus,
  type ToolAuthStatus,
} from "@/lib/hooks/useToolOAuthStatus";
import { hasPermission } from "@/lib/permissions";
import { useProjectsContext } from "@/lib/projects/providers";
import { useSettings } from "@/lib/settings/hooks";
import {
  CODING_AGENT_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  PYTHON_TOOL_ID,
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
} from "@/lib/tools/constants";
import { useAvailableTools, useBuiltInToolNames } from "@/lib/tools/hooks";
import { useToolsPopover } from "@/lib/tools/providers";
import { ToolSnapshot } from "@/lib/tools/types";
import { getAdminConfigureInfo, getToolTooltip } from "@/lib/tools/utils";
import { Permission } from "@/lib/types";
import EnabledCount from "@/refresh-components/EnabledCount";
import { useUser } from "@/providers/UserProvider";

// Names the hover group that swaps the source count for the disable button.
const HOVER_GROUP = "ToolLineItem";

/** A button the row can offer on its right. At most one of each renders. */
type ToolAction =
  | { kind: "authenticate"; authStatus: ToolAuthStatus }
  | { kind: "toggle"; count: { enabled: number; total: number } | null }
  | { kind: "configure"; href: string; tooltip: string }
  | { kind: "selectSources" };

export interface ToolLineItemProps {
  tool: ToolSnapshot;
}

/**
 * One action in the tools popover.
 *
 * Takes only the tool. Everything scoped to the popover — the agent, the
 * chat's tool configuration, the source counts — comes from
 * {@link useToolsPopover}, and everything scoped to the user — permissions,
 * which tools are configured, whether there are connectors — is a hook call
 * here. Nothing about a row is decided by its caller.
 */
export default function ToolLineItem({ tool }: ToolLineItemProps) {
  const t = useTranslations("actions");
  const router = useRouter();
  const {
    agent,
    toolConfiguration,
    sourceCounts,
    toggleForced,
    toggleEnabled,
    openSources,
    close,
  } = useToolsPopover();
  const { permissions } = useUser();
  const { vectorDbEnabled } = useSettings();
  const { tools: availableTools } = useAvailableTools();
  const builtInToolNames = useBuiltInToolNames();
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  const { currentProjectId } = useProjectsContext();
  const { getToolAuthStatus, authenticateTool } = useToolOAuthStatus(agent.id);

  const tooltipMessages = useMemo(
    () => ({
      descriptions: {
        [SEARCH_TOOL_ID]: t("toolsPopover.tooltips.search.description"),
        [IMAGE_GENERATION_TOOL_ID]: t(
          "toolsPopover.tooltips.imageGeneration.description"
        ),
        [WEB_SEARCH_TOOL_ID]: t("toolsPopover.tooltips.webSearch.description"),
        [PYTHON_TOOL_ID]: t("toolsPopover.tooltips.python.description"),
        [CODING_AGENT_TOOL_ID]: t(
          "toolsPopover.tooltips.codingAgent.description"
        ),
      },
      defaultDescription: t("toolsPopover.tooltips.default.description"),
      configure: t("toolsPopover.tooltips.configureSuffix.text"),
      askAdmin: t("toolsPopover.tooltips.askAdminSuffix.text"),
    }),
    [t]
  );
  const configureTooltips = useMemo(
    () => ({
      [IMAGE_GENERATION_TOOL_ID]: t(
        "toolsPopover.configureLinks.imageGeneration.tooltip"
      ),
      [WEB_SEARCH_TOOL_ID]: t("toolsPopover.configureLinks.webSearch.tooltip"),
      [PYTHON_TOOL_ID]: t(
        "toolsPopover.configureLinks.codeInterpreter.tooltip"
      ),
      openapi: t("toolsPopover.configureLinks.openapi.tooltip"),
    }),
    [t]
  );

  const isForced = toolConfiguration.forcedToolId === tool.id;
  // Switched off for this chat. The row stays interactive: pressing it turns
  // the tool back on and pins it in one gesture.
  const isDisabled = toolConfiguration.disabledToolIds.includes(tool.id);

  const isSearchTool = tool.in_code_tool_id === SEARCH_TOOL_ID;
  const inProject = currentProjectId != null;
  // Inside a project the row searches that project's files, so it neither
  // owns the connector sources nor offers a way into them.
  const ownsSources = isSearchTool && !inProject;
  const needsConnectors = ownsSources && ccPairs.length === 0;

  const isConfigured = availableTools.some(({ id }) => id === tool.id);
  // Search is advertised even when unconfigured, so an admin can go set it up.
  const isUnavailable = !isConfigured && !isSearchTool;

  const canManageActions = hasPermission(
    permissions,
    Permission.MANAGE_ACTIONS
  );
  const adminConfigure =
    isUnavailable && canManageActions
      ? getAdminConfigureInfo(tool, configureTooltips)
      : null;

  // A tool defined through the UI or served by MCP is named by whoever
  // created it, so its own name is all there is to show.
  const label =
    inProject && isSearchTool
      ? t("actionLineItem.projectSearch.label")
      : (builtInToolNames[tool.in_code_tool_id ?? ""] ??
        tool.display_name ??
        tool.name);

  // Only worth saying when the pin is narrowed to some of the sources.
  const sourcesNarrowed =
    ownsSources &&
    !needsConnectors &&
    isForced &&
    sourceCounts.enabled > 0 &&
    sourceCounts.enabled < sourceCounts.total;

  const authStatus = getToolAuthStatus(tool);
  const connectorsLabel = needsConnectors
    ? t("actionLineItem.addConnectors.label")
    : t("actionLineItem.configureConnectors.label");

  function handleClick() {
    if (isUnavailable) {
      toggleForced(tool.id);
      return;
    }
    if (isDisabled) toggleEnabled(tool.id);
    toggleForced(tool.id);
    // Pinning search is when its sources matter, so drill in rather than
    // dismissing. Releasing it just closes.
    if (ownsSources && !isForced) openSources();
    else close();
  }

  // Declared once because it renders both bare and hover-revealed, depending
  // on whether the action is already switched off.
  const toggleLabel = isDisabled
    ? t("actionLineItem.enable.label")
    : t("actionLineItem.disable.label");
  const toggleButton = (
    <Button
      icon={SvgSlash}
      onClick={() => toggleEnabled(tool.id)}
      prominence="internal"
      size="sm"
      aria-label={toggleLabel}
      tooltip={toggleLabel}
    />
  );

  // At most three: an authentication prompt, the enable/disable toggle, and
  // one of configure / select-sources. Declared in the order they render.
  const rightActions: ToolAction[] = [];
  if (!isUnavailable && tool.oauth_config_id && authStatus) {
    rightActions.push({ kind: "authenticate", authStatus });
  }
  if (!isUnavailable && !needsConnectors) {
    rightActions.push({
      kind: "toggle",
      count: sourcesNarrowed ? sourceCounts : null,
    });
  }
  // Exclusive by construction: an admin link needs a tool that is not search,
  // and sources belong to search. The `else` states what was only implied.
  if (adminConfigure) {
    rightActions.push({ kind: "configure", ...adminConfigure });
  } else if (ownsSources) {
    rightActions.push({ kind: "selectSources" });
  }

  function renderRightAction(action: ToolAction) {
    switch (action.kind) {
      case "authenticate":
        return (
          <Button
            icon={SvgKey}
            prominence="secondary"
            size="sm"
            aria-label={t("actionLineItem.authenticate.label")}
            onClick={() => {
              const { hasToken, isTokenExpired } = action.authStatus;
              if (!hasToken || isTokenExpired) void authenticateTool(tool);
            }}
          />
        );
      case "toggle":
        // The count takes the slot and reveals the toggle on hover. Without
        // it the toggle is bare once switched off, hover-revealed otherwise.
        if (action.count) {
          return (
            <Hoverable.Item
              group={HOVER_GROUP}
              variant="replace-on-hover"
              resting={
                <EnabledCount
                  enabledCount={action.count.enabled}
                  totalCount={action.count.total}
                />
              }
            >
              {toggleButton}
            </Hoverable.Item>
          );
        }
        return isDisabled ? (
          toggleButton
        ) : (
          <Hoverable.Item group={HOVER_GROUP}>{toggleButton}</Hoverable.Item>
        );
      case "configure":
        return (
          <Button
            icon={SvgSettings}
            prominence="tertiary"
            size="sm"
            tooltip={action.tooltip}
            onClick={() => {
              router.push(action.href as Route);
              close();
            }}
          />
        );
      case "selectSources":
        return (
          <Button
            icon={needsConnectors ? SvgSettings : SvgChevronRight}
            prominence="tertiary"
            size="sm"
            aria-label={connectorsLabel}
            tooltip={connectorsLabel}
            onClick={() => {
              if (needsConnectors) router.push("/admin/add-connector");
              else openSources();
            }}
          />
        );
    }
  }

  return (
    <Hoverable.Root group={HOVER_GROUP}>
      <LineItemButton
        title={label}
        icon={getIconForAction(tool)}
        sizePreset="main-ui"
        variant="section"
        rounding={2}
        state={isForced ? "selected" : "empty"}
        strikethrough={isDisabled}
        color={(isUnavailable && isForced) || isDisabled ? "muted" : undefined}
        disabled={needsConnectors || (isUnavailable && !isForced)}
        tooltip={getToolTooltip(
          tool,
          isConfigured,
          canManageActions,
          tooltipMessages
        )}
        onClick={handleClick}
        rightChildren={
          <Section gap={1} flexDirection="row">
            {rightActions.map((action) => (
              <Fragment key={action.kind}>{renderRightAction(action)}</Fragment>
            ))}
          </Section>
        }
      />
    </Hoverable.Root>
  );
}
