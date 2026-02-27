"use client";

import React from "react";
import { SEARCH_TOOL_ID } from "@/app/app/components/tools/constants";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { getIconForAction } from "@/app/app/services/actionUtils";
import { ToolAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import LineItem from "@/refresh-components/buttons/LineItem";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import IconButton from "@/refresh-components/buttons/IconButton";
import { Button } from "@opal/components";
import { cn, noProp } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import { SvgChevronRight, SvgKey, SvgSettings, SvgSlash } from "@opal/icons";
import { useProjectsContext } from "@/providers/ProjectsContext";
import { useRouter } from "next/navigation";
import type { Route } from "next";
import EnabledCount from "@/refresh-components/EnabledCount";
import { Section } from "@/layouts/general-layouts";

export interface ActionItemProps {
  tool?: ToolSnapshot;
  Icon?: React.FunctionComponent<IconProps>;
  label?: string;
  disabled: boolean;
  isForced: boolean;
  isUnavailable?: boolean;
  unavailableReason?: string;
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
  // Source counts for internal search tool
  sourceCounts?: { enabled: number; total: number };
}

export default function ActionLineItem({
  tool,
  Icon: ProvidedIcon,
  label: providedLabel,
  disabled,
  isForced,
  isUnavailable = false,
  unavailableReason,
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
  const router = useRouter();
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

  // Show source count when: internal search is pinned, has some (but not all) sources enabled
  const shouldShowSourceCount =
    isSearchToolAndNotInProject &&
    !isSearchToolWithNoConnectors &&
    isForced &&
    sourceCounts &&
    sourceCounts.enabled > 0 &&
    sourceCounts.enabled < sourceCounts.total;

  const tooltipText = isUnavailable ? unavailableReason : tool?.description;

  return (
    <SimpleTooltip tooltip={tooltipText} className="max-w-[30rem]">
      <div data-testid={`tool-option-${toolName}`}>
        <LineItem
          onClick={() => {
            if (isSearchToolWithNoConnectors) return;
            if (isUnavailable) {
              if (isForced) onForceToggle();
              return;
            }
            if (disabled) onToggle();
            onForceToggle();
            if (isSearchToolAndNotInProject && !isForced)
              onSourceManagementOpen?.();
            else onClose?.();
          }}
          selected={isForced}
          strikethrough={
            disabled || isSearchToolWithNoConnectors || isUnavailable
          }
          icon={Icon}
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

              {!isSearchToolWithNoConnectors && !isUnavailable && (
                <IconButton
                  icon={SvgSlash}
                  onClick={noProp(onToggle)}
                  internal
                  className={cn(
                    !disabled && "invisible group-hover/LineItem:visible",
                    // Hide when showing source count (it has its own hover behavior)
                    shouldShowSourceCount && "!hidden"
                  )}
                  tooltip={disabled ? "Enable" : "Disable"}
                />
              )}

              {isUnavailable && showAdminConfigure && adminConfigureHref && (
                <Button
                  icon={SvgSettings}
                  onClick={noProp(() => {
                    router.push(adminConfigureHref as Route);
                    onClose?.();
                  })}
                  prominence="tertiary"
                  size="sm"
                  tooltip={adminConfigureTooltip}
                />
              )}

              {/* Source count for internal search - show when some but not all sources selected AND tool is pinned */}
              {shouldShowSourceCount && (
                <span className="relative flex items-center whitespace-nowrap">
                  {/* Show count normally, disable icon on hover - both in same space */}
                  <span className="group-hover/LineItem:invisible">
                    <EnabledCount
                      enabledCount={sourceCounts.enabled}
                      totalCount={sourceCounts.total}
                    />
                  </span>
                  <span className="absolute inset-0 flex items-center justify-center invisible group-hover/LineItem:visible">
                    <Button
                      icon={SvgSlash}
                      onClick={noProp(onToggle)}
                      prominence="tertiary"
                      size="sm"
                      tooltip={disabled ? "Enable" : "Disable"}
                    />
                  </span>
                </span>
              )}

              {isSearchToolAndNotInProject && (
                <Button
                  icon={
                    isSearchToolWithNoConnectors ? SvgSettings : SvgChevronRight
                  }
                  onClick={noProp(() => {
                    if (isSearchToolWithNoConnectors)
                      router.push("/admin/add-connector");
                    else onSourceManagementOpen?.();
                  })}
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
        >
          {label}
        </LineItem>
      </div>
    </SimpleTooltip>
  );
}
