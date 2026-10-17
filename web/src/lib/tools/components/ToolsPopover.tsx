"use client";

import { useState, useCallback } from "react";
import { useTranslations } from "next-intl";
import { useFocusOnMount } from "@opal/hooks";
import { InputTypeIn, Button, Popover, PopoverMenu } from "@opal/components";
import { SvgSliders } from "@opal/icons";
import type { MinimalAgent } from "@/lib/agents/types";
import useCCPairs from "@/hooks/useCCPairs";
import { hasPermission } from "@/lib/permissions/utils";
import { useProjectsContext } from "@/lib/projects/providers";
import { useSettings } from "@/lib/settings/hooks";
import { FILE_READER_TOOL_ID, SEARCH_TOOL_ID } from "@/lib/tools/constants";
import {
  useBuiltInToolNames,
  type ToolConfigurationHandle,
} from "@/lib/tools/hooks";
import { ToolsPopoverProvider } from "@/lib/tools/providers";
import SourcesView from "@/lib/tools/components/SourcesView";
import ToolLineItem from "@/lib/tools/components/ToolLineItem";
import { Permission } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";

export interface ToolsPopoverProps {
  agent: MinimalAgent;
  toolConfiguration: ToolConfigurationHandle;
  disabled?: boolean;
}

export default function ToolsPopover({
  agent,
  toolConfiguration,
  disabled = false,
}: ToolsPopoverProps) {
  const t = useTranslations("actions");
  const builtInToolNames = useBuiltInToolNames();
  const [open, setOpen] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const focusOnMount = useFocusOnMount<HTMLInputElement>();
  const { permissions } = useUser();
  const { vectorDbEnabled } = useSettings();
  const { ccPairs } = useCCPairs(vectorDbEnabled);
  const { currentProjectId, allCurrentProjectFiles } = useProjectsContext();
  const hasNoConnectors = ccPairs.length === 0;
  const close = useCallback(() => setOpen(false), []);
  const openSources = useCallback(() => setShowSources(true), []);

  const displayTools = agent.tools.filter((tool) => {
    if (!tool.in_code_tool_id || tool.mcp_server_id) return false;
    if (!tool.chat_selectable) return false;
    if (tool.in_code_tool_id === FILE_READER_TOOL_ID) return false;

    if (tool.in_code_tool_id === SEARCH_TOOL_ID && !!currentProjectId) {
      return Boolean(allCurrentProjectFiles?.length);
    }
    if (
      tool.in_code_tool_id === SEARCH_TOOL_ID &&
      hasPermission(permissions, Permission.MANAGE_CONNECTORS)
    ) {
      return true;
    }
    if (
      tool.in_code_tool_id === SEARCH_TOOL_ID &&
      hasNoConnectors &&
      !hasPermission(permissions, Permission.MANAGE_CONNECTORS)
    ) {
      return false;
    }
    return true;
  });

  const filteredTools = displayTools.filter((tool) => {
    if (!searchTerm) return true;
    const searchLower = searchTerm.toLowerCase();
    const shownName =
      currentProjectId != null && tool.in_code_tool_id === SEARCH_TOOL_ID
        ? t("actionLineItem.projectSearch.label")
        : (builtInToolNames[tool.in_code_tool_id ?? ""] ?? tool.display_name);
    return (
      shownName?.toLowerCase().includes(searchLower) ||
      tool.display_name?.toLowerCase().includes(searchLower) ||
      tool.name.toLowerCase().includes(searchLower) ||
      tool.description?.toLowerCase().includes(searchLower)
    );
  });

  if (displayTools.length === 0) return null;

  return (
    <ToolsPopoverProvider
      agent={agent}
      toolConfiguration={toolConfiguration}
      openSources={openSources}
      close={close}
    >
      <Popover
        open={open}
        onOpenChange={(next) => {
          setOpen(next);
          if (next) {
            setShowSources(false);
            setSearchTerm("");
          }
        }}
      >
        <Popover.Trigger asChild>
          <div data-testid="action-management-toggle">
            <Button
              disabled={disabled}
              icon={SvgSliders}
              interaction={open ? "hover" : "rest"}
              prominence="tertiary"
              tooltip={t("toolsPopover.manageActions.tooltip")}
            />
          </div>
        </Popover.Trigger>
        <Popover.Content side="bottom" align="start" width="lg">
          <div data-testid="tool-options">
            {showSources ? (
              <SourcesView onBack={() => setShowSources(false)} />
            ) : (
              <PopoverMenu>
                {[
                  <InputTypeIn
                    key="search"
                    placeholder={t("toolsPopover.search.placeholder")}
                    searchIcon
                    value={searchTerm}
                    onChange={(event) => setSearchTerm(event.target.value)}
                    ref={focusOnMount}
                    variant="internal"
                  />,
                  ...filteredTools.map((tool) => (
                    <ToolLineItem key={tool.id} tool={tool} />
                  )),
                ]}
              </PopoverMenu>
            )}
          </div>
        </Popover.Content>
      </Popover>
    </ToolsPopoverProvider>
  );
}
