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

export interface ActionItemProps {
  tool?: ToolSnapshot;
  Icon?: React.FunctionComponent<IconProps>;
  label?: string;
  disabled: boolean;
  isForced: boolean;
  onToggle: () => void;
  onForceToggle: () => void;
  onSourceManagementOpen?: () => void;
  hasNoConnectors?: boolean;
  toolAuthStatus?: ToolAuthStatus;
  onOAuthAuthenticate?: () => void;
}

export default function ActionLineItem({
  tool,
  Icon: ProvidedIcon,
  label: providedLabel,
  disabled,
  isForced,
  onToggle,
  onForceToggle,
  onSourceManagementOpen,
  hasNoConnectors = false,
  toolAuthStatus,
  onOAuthAuthenticate,
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

  return (
    <SimpleTooltip tooltip={tool?.description} className="max-w-[30rem]">
      <div data-testid={`tool-option-${toolName}`}>
        <LineItem
          onClick={() => {
            if (isSearchToolWithNoConnectors) return;
            if (disabled) onToggle();
            onForceToggle();
          }}
          selected={isForced}
          strikethrough={disabled || isSearchToolWithNoConnectors}
          icon={Icon}
          rightChildren={
            <div className="flex flex-row items-center gap-1">
              {tool?.oauth_config_id && toolAuthStatus && (
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

              {!isSearchToolWithNoConnectors && (
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
              {tool &&
                tool.in_code_tool_id === SEARCH_TOOL_ID &&
                !currentProjectId && (
                  <IconButton
                    icon={
                      isSearchToolWithNoConnectors
                        ? SvgSettings
                        : SvgChevronRight
                    }
                    onClick={noProp(() => {
                      if (isSearchToolWithNoConnectors)
                        window.location.href = "/admin/add-connector";
                      else onSourceManagementOpen?.();
                    })}
                    internal
                    className={cn(
                      isSearchToolWithNoConnectors &&
                        "invisible group-hover/LineItem:visible"
                    )}
                    tooltip={
                      isSearchToolWithNoConnectors
                        ? "Setup Connectors"
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
