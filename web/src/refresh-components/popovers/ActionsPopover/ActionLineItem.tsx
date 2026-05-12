"use client";

import React from "react";
import { SEARCH_TOOL_ID } from "@/app/app/components/tools/constants";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { getIconForAction } from "@/app/app/services/actionUtils";
import { ToolAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import { Button, LineItemButton } from "@opal/components";
import { noProp } from "@/lib/utils";
import { markdown } from "@opal/utils";
import type { IconProps } from "@opal/types";
import { SvgChevronRight, SvgKey, SvgSettings, SvgSlash } from "@opal/icons";
import { useProjectsContext } from "@/providers/ProjectsContext";
import type { Route } from "next";
import EnabledCount from "@/refresh-components/EnabledCount";
import { Section } from "@/layouts/general-layouts";
import { Hoverable } from "@opal/core";

export interface ActionItemProps {
  tool?: ToolSnapshot;
  Icon?: React.FunctionComponent<IconProps>;
  label?: string;
  disabled: boolean;
  isForced: boolean;
  isUnavailable?: boolean;
  tooltip?: string;
  showAdminConfigure?: boolean;
  adminConfigureHref?: string;
  adminConfigureTooltip?: string;
  onToggle: () => void;
  onForceToggle: () => void;
  onSourceManagementOpen?: () => void;
  hasNoConnectors?: boolean;
  toolAuthStatus?: ToolAuthStatus;
  onOAuthAuthenticate?: () => void;
  onClose?: () => void;
  sourceCounts?: { enabled: number; total: number };
}

export default function ActionLineItem({
  tool,
  Icon: ProvidedIcon,
  label: providedLabel,
  disabled,
  isForced,
  isUnavailable = false,
  tooltip,
  showAdminConfigure = false,
  adminConfigureHref,
  adminConfigureTooltip = "Configure",
  onToggle,
  onForceToggle,
  onSourceManagementOpen,
  hasNoConnectors = false,
  toolAuthStatus,
  onOAuthAuthenticate,
  onClose,
  sourceCounts,
}: ActionItemProps) {
  const { currentProjectId } = useProjectsContext();

  const Icon = tool ? getIconForAction(tool) : ProvidedIcon!;
  const toolName = tool?.name || providedLabel || "";

  let label = tool ? tool.display_name || tool.name : providedLabel!;
  if (!!currentProjectId && tool?.in_code_tool_id === SEARCH_TOOL_ID) {
    label = "Project Search";
  }

  const isSearchToolWithNoConnectors =
    !currentProjectId &&
    tool?.in_code_tool_id === SEARCH_TOOL_ID &&
    hasNoConnectors;

  const isSearchToolAndNotInProject =
    tool?.in_code_tool_id === SEARCH_TOOL_ID && !currentProjectId;

  const shouldShowSourceCount =
    isSearchToolAndNotInProject &&
    !isSearchToolWithNoConnectors &&
    isForced &&
    sourceCounts &&
    sourceCounts.enabled > 0 &&
    sourceCounts.enabled < sourceCounts.total;

  const tooltipText = tooltip || tool?.description;

  return (
    <Hoverable.Root group="action-row" data-testid={`tool-option-${toolName}`}>
      <LineItemButton
        sizePreset="main-ui"
        variant="section"
        rounding="sm"
        center
        onClick={() => {
          if (isUnavailable) {
            onForceToggle();
            return;
          }
          if (disabled) onToggle();
          onForceToggle();
          if (isSearchToolAndNotInProject && !isForced)
            onSourceManagementOpen?.();
          else onClose?.();
        }}
        state={isForced ? "selected" : "empty"}
        disabled={isSearchToolWithNoConnectors || (isUnavailable && !isForced)}
        color={
          disabled || (isUnavailable && isForced) ? "muted" : "interactive"
        }
        title={disabled ? markdown(`~~${label}~~`) : label}
        icon={Icon}
        tooltip={tooltipText}
        tooltipSide="right"
        rightChildren={
          <Section gap={0.25} flexDirection="row">
            {!isUnavailable && tool?.oauth_config_id && toolAuthStatus && (
              <Button
                icon={SvgKey}
                prominence="secondary"
                size="sm"
                onClick={noProp(() => {
                  if (
                    !toolAuthStatus.hasToken ||
                    toolAuthStatus.isTokenExpired
                  ) {
                    onOAuthAuthenticate?.();
                  }
                })}
              />
            )}

            {!isSearchToolWithNoConnectors &&
              !isUnavailable &&
              !shouldShowSourceCount &&
              (disabled ? (
                <Button
                  icon={SvgSlash}
                  onClick={noProp(onToggle)}
                  prominence="internal"
                  size="sm"
                  aria-label="Enable"
                  tooltip="Enable"
                />
              ) : (
                <Hoverable.Item group="action-row" variant="appear-on-hover">
                  <Button
                    icon={SvgSlash}
                    onClick={noProp(onToggle)}
                    prominence="internal"
                    size="sm"
                    aria-label="Disable"
                    tooltip="Disable"
                  />
                </Hoverable.Item>
              ))}

            {isUnavailable && showAdminConfigure && adminConfigureHref && (
              <Button
                icon={SvgSettings}
                href={adminConfigureHref as Route}
                prominence="tertiary"
                size="sm"
                tooltip={adminConfigureTooltip}
              />
            )}

            {shouldShowSourceCount && (
              <div className="relative flex items-center whitespace-nowrap">
                <Hoverable.Item group="action-row" variant="appear-on-rest">
                  <EnabledCount
                    enabledCount={sourceCounts.enabled}
                    totalCount={sourceCounts.total}
                  />
                </Hoverable.Item>
                <div className="absolute inset-0 flex items-center justify-center">
                  <Hoverable.Item group="action-row" variant="appear-on-hover">
                    <Button
                      icon={SvgSlash}
                      onClick={noProp(onToggle)}
                      prominence="tertiary"
                      size="sm"
                      tooltip="Disable"
                    />
                  </Hoverable.Item>
                </div>
              </div>
            )}

            {isSearchToolAndNotInProject && (
              <Button
                aria-label={
                  isSearchToolWithNoConnectors
                    ? "Add Connectors"
                    : "Configure Connectors"
                }
                icon={
                  isSearchToolWithNoConnectors ? SvgSettings : SvgChevronRight
                }
                href={
                  isSearchToolWithNoConnectors
                    ? ("/admin/add-connector" as Route)
                    : undefined
                }
                onClick={
                  isSearchToolWithNoConnectors
                    ? undefined
                    : noProp(onSourceManagementOpen)
                }
                prominence="tertiary"
                size="sm"
                tooltip={
                  isSearchToolWithNoConnectors
                    ? "Add Connectors"
                    : "Configure Connectors"
                }
              />
            )}
          </Section>
        }
      />
    </Hoverable.Root>
  );
}
