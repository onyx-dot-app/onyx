"use client";

import React, { useMemo } from "react";
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
import { useActionsContext, ToolState } from "@/contexts/ActionsContext";

export interface ActionItemProps {
  tool?: ToolSnapshot;
  Icon?: React.FunctionComponent<IconProps>;
  label?: string;
  onSourceManagementOpen?: () => void;
  hasNoConnectors?: boolean;
  toolAuthStatus?: ToolAuthStatus;
  onOAuthAuthenticate?: () => void;
  isProjectContext?: boolean;
}

export default function ActionLineItem({
  tool,
  Icon: ProvidedIcon,
  label: providedLabel,
  onSourceManagementOpen,
  hasNoConnectors = false,
  toolAuthStatus,
  onOAuthAuthenticate,
  isProjectContext = false,
}: ActionItemProps) {
  const { toolMap, setToolStatus } = useActionsContext();
  const Icon = tool ? getIconForAction(tool) : ProvidedIcon!;
  const toolName = tool?.name || providedLabel || "";

  const toolState = useMemo(() => {
    if (!tool) return ToolState.Enabled;
    return toolMap[tool.id] ?? ToolState.Enabled;
  }, [tool, toolMap]);
  const disabled = toolState === ToolState.Disabled;
  const isForced = toolState === ToolState.Forced;

  let label = tool ? tool.display_name || tool.name : providedLabel!;
  if (isProjectContext && tool?.in_code_tool_id === SEARCH_TOOL_ID) {
    label = "Project Search";
  }

  const isSearchToolWithNoConnectors =
    !isProjectContext &&
    tool?.in_code_tool_id === SEARCH_TOOL_ID &&
    hasNoConnectors;

  const handleToggle = () => {
    if (!tool) return;
    const target = disabled ? ToolState.Enabled : ToolState.Disabled;
    setToolStatus(tool.id, target);
  };

  const handleForceToggle = () => {
    if (!tool) return;
    const target =
      toolState === ToolState.Forced ? ToolState.Enabled : ToolState.Forced;
    // If currently disabled, first enable so forcing makes sense
    if (toolState === ToolState.Disabled) {
      setToolStatus(tool.id, ToolState.Enabled);
    }
    setToolStatus(tool.id, target);
  };

  return (
    <SimpleTooltip tooltip={tool?.description} className="max-w-[30rem]">
      <div data-testid={`tool-option-${toolName}`}>
        <LineItem
          onClick={() => {
            if (isSearchToolWithNoConnectors) return;
            if (disabled) handleToggle();
            handleForceToggle();
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
                  onClick={noProp(handleToggle)}
                  internal
                  className={cn(
                    !disabled && "invisible group-hover/LineItem:visible"
                  )}
                  tooltip={disabled ? "Enable" : "Disable"}
                />
              )}
              {tool &&
                tool.in_code_tool_id === SEARCH_TOOL_ID &&
                !isProjectContext && (
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
