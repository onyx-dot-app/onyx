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
import { useProjectsContext } from "@/app/chat/projects/ProjectsContext";
import { useRouter } from "next/navigation";

export interface ActionItemProps {
  tool: ToolSnapshot;
  Icon?: React.FunctionComponent<IconProps>;
  onSourceManagementOpen?: () => void;
  hasNoConnectors?: boolean;
  toolAuthStatus?: ToolAuthStatus;
  onOAuthAuthenticate?: () => void;
  onClose?: () => void;
}

export default function ActionLineItem({
  tool,
  Icon: ProvidedIcon,
  onSourceManagementOpen,
  hasNoConnectors = false,
  toolAuthStatus,
  onOAuthAuthenticate,
  onClose,
}: ActionItemProps) {
  const { currentProjectId } = useProjectsContext();
  const isProjectContext = !!currentProjectId;
  const router = useRouter();
  const { toolMap, setToolStatus } = useActionsContext();

  const Icon = tool ? getIconForAction(tool) : ProvidedIcon!;
  const toolName = tool.name;

  const toolState = useMemo(() => {
    return toolMap[tool.id] ?? ToolState.Enabled;
  }, [tool, toolMap]);
  const disabled = toolState === ToolState.Disabled;
  const isForced = toolState === ToolState.Forced;

  const label =
    isProjectContext && tool.in_code_tool_id === SEARCH_TOOL_ID
      ? "Project Search"
      : tool.display_name;

  const isSearchToolWithNoConnectors =
    !isProjectContext &&
    tool.in_code_tool_id === SEARCH_TOOL_ID &&
    hasNoConnectors;

  function handleToggle() {
    const target = isForced ? ToolState.Enabled : ToolState.Forced;
    setToolStatus(tool.id, target);
  }

  function handleDisable() {
    // const target = disabled ? ToolState.Enabled : ToolState.Enabled;
    setToolStatus(tool.id, ToolState.Disabled);
  }
  const isSearchToolAndNotInProject =
    tool?.in_code_tool_id === SEARCH_TOOL_ID && !currentProjectId;

  return (
    <SimpleTooltip tooltip={tool.description}>
      <div data-testid={`tool-option-${toolName}`}>
        <LineItem
          onClick={() => {
            if (isSearchToolWithNoConnectors) return;
            handleToggle();
            if (isSearchToolAndNotInProject && !isForced)
              onSourceManagementOpen?.();
            else onClose?.();
          }}
          selected={isForced}
          strikethrough={disabled || isSearchToolWithNoConnectors}
          icon={Icon}
          rightChildren={
            <div className="flex flex-row items-center gap-1">
              {tool.oauth_config_id && toolAuthStatus && (
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
                  onClick={noProp(handleDisable)}
                  internal
                  className={cn(
                    !disabled && "invisible group-hover/LineItem:visible"
                  )}
                  tooltip={disabled ? "Enable" : "Disable"}
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
