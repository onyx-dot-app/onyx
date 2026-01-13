"use client";

import React from "react";
import { SEARCH_TOOL_ID } from "@/app/chat/components/tools/constants";
import { ToolSnapshot } from "@/lib/tools/interfaces";
import { getIconForAction } from "@/app/chat/services/actionUtils";
import { ToolAuthStatus } from "@/lib/hooks/useToolOAuthStatus";
import LineItem from "@/refresh-components/buttons/LineItem";
import SimpleTooltip from "@/refresh-components/SimpleTooltip";
import IconButton from "@/refresh-components/buttons/IconButton";
import { cn, noProp } from "@/lib/utils";
import type { IconProps } from "@opal/types";
import { SvgChevronRight, SvgKey, SvgSettings, SvgSlash } from "@opal/icons";
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useRouter } from "next/navigation";
import type { Route } from "next";

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
            <div className="flex flex-row items-center gap-1">
              {!isUnavailable && tool?.oauth_config_id && toolAuthStatus && (
                <IconButton
                  icon={({ className }) => (
                    <SvgKey
                      className={cn(
                        className,
                        "stroke-yellow-500 hover:stroke-yellow-600"
                      )}
                    />
                  )}
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
                    !disabled && "invisible group-hover/LineItem:visible"
                  )}
                  tooltip={disabled ? "Enable" : "Disable"}
                />
              )}
              {isUnavailable && showAdminConfigure && adminConfigureHref && (
                <IconButton
                  icon={SvgSettings}
                  onClick={noProp(() => {
                    router.push(adminConfigureHref as Route);
                    onClose?.();
                  })}
                  internal
                  tooltip={adminConfigureTooltip}
                />
              )}
              {isSearchToolAndNotInProject && (
                <IconButton
                  icon={
                    isSearchToolWithNoConnectors ? SvgSettings : SvgChevronRight
                  }
                  onClick={noProp(() => {
                    if (isSearchToolWithNoConnectors)
                      router.push("/admin/add-connector");
                    else onSourceManagementOpen?.();
                  })}
                  internal
                  className={cn(
                    isSearchToolWithNoConnectors &&
                      "invisible group-hover/LineItem:visible"
                  )}
                  tooltip={
                    isSearchToolWithNoConnectors
                      ? "Add Connectors"
                      : "Configure Connectors"
                  }
                />
              )}
            </div>
          }
        >
          {label}
        </LineItem>
      </div>
    </SimpleTooltip>
  );
}
