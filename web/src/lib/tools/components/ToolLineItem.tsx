"use client";

import { useRouter } from "next/navigation";
import type { Route } from "next";
import { Button, LineItemButton } from "@opal/components";
import { Hoverable } from "@opal/core";
import { SvgChevronRight, SvgKey, SvgSettings, SvgSlash } from "@opal/icons";
import { getIconForAction } from "@/app/app/services/actionUtils";
import useCCPairs from "@/hooks/useCCPairs";
import { Section } from "@/layouts/general-layouts";
import { useToolOAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import { hasPermission } from "@/lib/permissions";
import { useProjectsContext } from "@/lib/projects/providers";
import { useSettings } from "@/lib/settings/hooks";
import { SEARCH_TOOL_ID } from "@/lib/tools/constants";
import { useAvailableTools } from "@/lib/tools/hooks";
import { useToolsPopover } from "@/lib/tools/providers";
import { ToolSnapshot } from "@/lib/tools/types";
import { getAdminConfigureInfo, getToolTooltip } from "@/lib/tools/utils";
import { Permission } from "@/lib/types";
import EnabledCount from "@/refresh-components/EnabledCount";
import { useUser } from "@/providers/UserProvider";

// Names the hover group that swaps the source count for the disable button.
const HOVER_GROUP = "ToolLineItem";

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
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  const { currentProjectId } = useProjectsContext();
  const { getToolAuthStatus, authenticateTool } = useToolOAuthStatus(agent.id);

  const isForced = toolConfiguration.forcedToolId === tool.id;
  // Switched off for this chat. The row stays interactive: pressing it turns
  // the tool back on and pins it in one gesture.
  const isOff = toolConfiguration.disabledToolIds.includes(tool.id);

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
    isUnavailable && canManageActions ? getAdminConfigureInfo(tool) : null;

  const label =
    inProject && isSearchTool
      ? "Project Search"
      : tool.display_name || tool.name;

  // Only worth saying when the pin is narrowed to some of the sources.
  const showSourceCount =
    ownsSources &&
    !needsConnectors &&
    isForced &&
    sourceCounts.enabled > 0 &&
    sourceCounts.enabled < sourceCounts.total;

  const authStatus = getToolAuthStatus(tool);
  const connectorsLabel = needsConnectors
    ? "Add Connectors"
    : "Configure Connectors";

  function handleClick() {
    if (isUnavailable) {
      toggleForced(tool.id);
      return;
    }
    if (isOff) toggleEnabled(tool.id);
    toggleForced(tool.id);
    // Pinning search is when its sources matter, so drill in rather than
    // dismissing. Releasing it just closes.
    if (ownsSources && !isForced) openSources();
    else close();
  }

  // Declared once because it renders both bare and hover-revealed, depending
  // on whether the action is already switched off.
  const toggleButton = (
    <Button
      icon={SvgSlash}
      onClick={() => toggleEnabled(tool.id)}
      prominence="internal"
      size="sm"
      aria-label={isOff ? "Enable" : "Disable"}
      tooltip={isOff ? "Enable" : "Disable"}
    />
  );

  return (
    <Hoverable.Root group={HOVER_GROUP}>
      <LineItemButton
        title={label}
        icon={getIconForAction(tool)}
        sizePreset="main-ui"
        variant="section"
        state={isForced ? "selected" : "empty"}
        strikethrough={isOff}
        color={isUnavailable && isForced ? "muted" : undefined}
        disabled={needsConnectors || (isUnavailable && !isForced)}
        tooltip={getToolTooltip(tool, isConfigured, canManageActions)}
        onClick={handleClick}
        rightChildren={
          <Section gap={1} flexDirection="row">
            {!isUnavailable && tool.oauth_config_id && authStatus && (
              <Button
                icon={SvgKey}
                prominence="secondary"
                size="sm"
                aria-label="Authenticate"
                onClick={() => {
                  if (!authStatus.hasToken || authStatus.isTokenExpired) {
                    void authenticateTool(tool);
                  }
                }}
              />
            )}

            {!needsConnectors &&
              !isUnavailable &&
              // The source count owns this slot when shown, and brings the
              // toggle with it.
              !showSourceCount &&
              (isOff ? (
                toggleButton
              ) : (
                <Hoverable.Item group={HOVER_GROUP}>
                  {toggleButton}
                </Hoverable.Item>
              ))}

            {adminConfigure && (
              <Button
                icon={SvgSettings}
                prominence="tertiary"
                size="sm"
                tooltip={adminConfigure.tooltip}
                onClick={() => {
                  router.push(adminConfigure.href as Route);
                  close();
                }}
              />
            )}

            {showSourceCount && (
              <Hoverable.Item
                group={HOVER_GROUP}
                variant="replace-on-hover"
                resting={
                  <EnabledCount
                    enabledCount={sourceCounts.enabled}
                    totalCount={sourceCounts.total}
                  />
                }
              >
                {toggleButton}
              </Hoverable.Item>
            )}

            {ownsSources && (
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
            )}
          </Section>
        }
      />
    </Hoverable.Root>
  );
}
