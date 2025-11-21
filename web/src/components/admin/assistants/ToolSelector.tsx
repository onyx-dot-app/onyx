"use client";

import React, {
  useMemo,
  useCallback,
  useState,
  useRef,
  useEffect,
} from "react";
import { BooleanFormField } from "@/components/Field";
import { ToolSnapshot, MCPServer } from "@/lib/tools/interfaces";
import { FastField } from "formik";
import { MCPServerSection } from "./FormSections";
import { MemoizedToolList } from "./MemoizedToolCheckboxes";
import Text from "@/refresh-components/texts/Text";
import {
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
} from "@/app/chat/components/tools/constants";
import { HoverPopup } from "@/components/HoverPopup";
import { Info } from "lucide-react";

interface ToolSelectorProps {
  tools: ToolSnapshot[];
  mcpServers?: MCPServer[];
  enabledToolsMap: { [key: number]: boolean };
  setFieldValue?: (field: string, value: any) => void;
  imageGenerationDisabled?: boolean;
  imageGenerationDisabledTooltip?: string;
  searchToolDisabled?: boolean;
  searchToolDisabledTooltip?: string;
  hideSearchTool?: boolean;
}

export function ToolSelector({
  tools,
  mcpServers = [],
  enabledToolsMap,
  setFieldValue,
  imageGenerationDisabled = false,
  imageGenerationDisabledTooltip,
  searchToolDisabled = false,
  searchToolDisabledTooltip,
  hideSearchTool = false,
}: ToolSelectorProps) {
  const searchTool = tools.find((t) => t.in_code_tool_id === SEARCH_TOOL_ID);
  const webSearchTool = tools.find(
    (t) => t.in_code_tool_id === WEB_SEARCH_TOOL_ID
  );
  const imageGenerationTool = tools.find(
    (t) => t.in_code_tool_id === IMAGE_GENERATION_TOOL_ID
  );

  const { mcpTools, customTools, mcpToolsByServer } = useMemo(() => {
    const allCustom = tools.filter(
      (tool) =>
        tool.in_code_tool_id !== SEARCH_TOOL_ID &&
        tool.in_code_tool_id !== IMAGE_GENERATION_TOOL_ID &&
        tool.in_code_tool_id !== WEB_SEARCH_TOOL_ID
    );

    const mcp = allCustom.filter((tool) => tool.mcp_server_id);
    const custom = allCustom.filter((tool) => !tool.mcp_server_id);

    const groups: { [serverId: number]: ToolSnapshot[] } = {};
    mcp.forEach((tool) => {
      if (tool.mcp_server_id) {
        if (!groups[tool.mcp_server_id]) {
          groups[tool.mcp_server_id] = [];
        }
        groups[tool.mcp_server_id]!.push(tool);
      }
    });

    return { mcpTools: mcp, customTools: custom, mcpToolsByServer: groups };
  }, [tools]);

  const [collapsedServers, setCollapsedServers] = useState<Set<number>>(
    () => new Set(Object.keys(mcpToolsByServer).map((id) => parseInt(id, 10)))
  );

  const seenServerIdsRef = useRef<Set<number>>(
    new Set(Object.keys(mcpToolsByServer).map((id) => parseInt(id, 10)))
  );

  useEffect(() => {
    const serverIds = Object.keys(mcpToolsByServer).map((id) =>
      parseInt(id, 10)
    );
    const unseenIds = serverIds.filter(
      (id) => !seenServerIdsRef.current.has(id)
    );

    if (unseenIds.length === 0) return;

    const updatedSeen = new Set(seenServerIdsRef.current);
    unseenIds.forEach((id) => updatedSeen.add(id));
    seenServerIdsRef.current = updatedSeen;

    setCollapsedServers((prev) => {
      const next = new Set(prev);
      unseenIds.forEach((id) => next.add(id));
      return next;
    });
  }, [mcpToolsByServer]);

  const toggleServerCollapse = useCallback((serverId: number) => {
    setCollapsedServers((prev) => {
      const next = new Set(prev);
      if (next.has(serverId)) {
        next.delete(serverId);
      } else {
        next.add(serverId);
      }
      return next;
    });
  }, []);

  const toggleMCPServerTools = useCallback(
    (serverId: number) => {
      if (!setFieldValue) return;

      const serverTools = mcpToolsByServer[serverId] || [];
      const enabledCount = serverTools.filter(
        (tool) => enabledToolsMap[tool.id]
      ).length;
      const shouldEnable = enabledCount !== serverTools.length;

      const updatedMap = { ...enabledToolsMap };
      serverTools.forEach((tool) => {
        updatedMap[tool.id] = shouldEnable;
      });

      setFieldValue("enabled_tools_map", updatedMap);
    },
    [mcpToolsByServer, enabledToolsMap, setFieldValue]
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-1.5 mb-2">
        <Text mainUiBody text04>
          Built-in Actions
        </Text>
        <HoverPopup
          mainContent={
            <Info className="h-3.5 w-3.5 text-text-400 cursor-help" />
          }
          popupContent={
            <div className="text-xs space-y-2 max-w-xs">
              <div>
                <span className="font-semibold">Web Search:</span> Configure a
                provider on the Web Search admin page to enable this tool.
              </div>
              <div>
                <span className="font-semibold">Image Generation:</span> Add an
                OpenAI LLM provider with an API key under Admin → Configuration
                → LLM.
              </div>
            </div>
          }
          direction="bottom"
        />
      </div>
      {!hideSearchTool && searchTool && (
        <FastField name={`enabled_tools_map.${searchTool.id}`}>
          {() => (
            <BooleanFormField
              name={`enabled_tools_map.${searchTool.id}`}
              label={searchTool.display_name}
              subtext="Search through your organization's knowledge base and documents"
              disabled={searchToolDisabled}
              disabledTooltip={searchToolDisabledTooltip}
            />
          )}
        </FastField>
      )}

      {webSearchTool && (
        <FastField name={`enabled_tools_map.${webSearchTool.id}`}>
          {() => (
            <BooleanFormField
              name={`enabled_tools_map.${webSearchTool.id}`}
              label={webSearchTool.display_name}
              subtext="Access real-time information and search the web for up-to-date results"
            />
          )}
        </FastField>
      )}

      {imageGenerationTool && (
        <FastField name={`enabled_tools_map.${imageGenerationTool.id}`}>
          {() => (
            <BooleanFormField
              name={`enabled_tools_map.${imageGenerationTool.id}`}
              label={imageGenerationTool.display_name}
              subtext="Generate and manipulate images using AI-powered tools."
              disabled={imageGenerationDisabled}
              disabledTooltip={imageGenerationDisabledTooltip}
            />
          )}
        </FastField>
      )}

      {customTools.length > 0 && (
        <>
          <Text mainUiBody text04 className="mb-2">
            OpenAPI Actions
          </Text>
          <MemoizedToolList tools={customTools} />
        </>
      )}

      {Object.keys(mcpToolsByServer).length > 0 && (
        <>
          <Text mainUiBody text04 className="mb-2">
            MCP Actions
          </Text>
          {Object.entries(mcpToolsByServer).map(([serverId, serverTools]) => {
            const serverIdNum = parseInt(serverId);
            const serverInfo =
              mcpServers.find((server) => server.id === serverIdNum) || null;
            const isCollapsed = collapsedServers.has(serverIdNum);

            const firstTool = serverTools[0];
            const serverName =
              serverInfo?.name ||
              firstTool?.name?.split("_").slice(0, -1).join("_") ||
              `MCP Server ${serverId}`;
            const serverUrl = serverInfo?.server_url || "Unknown URL";

            return (
              <MCPServerSection
                key={`mcp-server-${serverId}`}
                serverId={serverIdNum}
                serverTools={serverTools}
                serverName={serverName}
                serverUrl={serverUrl}
                isCollapsed={isCollapsed}
                onToggleCollapse={toggleServerCollapse}
                onToggleServerTools={() => toggleMCPServerTools(serverIdNum)}
              />
            );
          })}
        </>
      )}
    </div>
  );
}
