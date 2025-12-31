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
import { MCPServerSection } from "./FormSections";
import { MemoizedToolList } from "./MemoizedToolCheckboxes";
import Text from "@/refresh-components/texts/Text";
import {
  SEARCH_TOOL_ID,
  WEB_SEARCH_TOOL_ID,
  IMAGE_GENERATION_TOOL_ID,
  PYTHON_TOOL_ID,
  OPEN_URL_TOOL_ID,
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
  const pythonTool = tools.find((t) => t.in_code_tool_id === PYTHON_TOOL_ID);
  const openUrlTool = tools.find((t) => t.in_code_tool_id === OPEN_URL_TOOL_ID);

  // Check if Web Search is enabled - if so, OpenURL must be enabled
  const isWebSearchEnabled = webSearchTool && enabledToolsMap[webSearchTool.id];
  const isOpenUrlForced = isWebSearchEnabled;

  const { mcpTools, customTools, mcpToolsByServer } = useMemo(() => {
    const allCustom = tools.filter(
      (tool) =>
        tool.in_code_tool_id !== SEARCH_TOOL_ID &&
        tool.in_code_tool_id !== IMAGE_GENERATION_TOOL_ID &&
        tool.in_code_tool_id !== WEB_SEARCH_TOOL_ID &&
        tool.in_code_tool_id !== PYTHON_TOOL_ID &&
        tool.in_code_tool_id !== OPEN_URL_TOOL_ID
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
        <Text as="p" mainUiBody text04>
          Built-in Actions
        </Text>
        <HoverPopup
          mainContent={
            <Info className="h-3.5 w-3.5 text-text-400 cursor-help" />
          }
          popupContent={
            <div className="text-xs space-y-2 max-w-xs bg-background-neutral-dark-03 text-text-light-05">
              <div>
                <span className="font-semibold">Internal Search:</span> Requires
                at least one connector to be configured to search your
                organization&apos;s knowledge base.
              </div>
              <div>
                <span className="font-semibold">Web Search:</span> Configure a
                provider on the Web Search admin page to enable this tool.
              </div>
              <div>
                <span className="font-semibold">Image Generation:</span> Add an
                OpenAI LLM provider with an API key under Admin → Configuration
                → LLM.
              </div>
              <div>
                <span className="font-semibold">Code Interpreter:</span>{" "}
                Requires the Code Interpreter service to be configured with a
                valid base URL.
              </div>
              <div>
                <div>
                  <span className="font-semibold">Open URL:</span> Open and read
                  the content of URLs provided in the conversation.
                </div>
                {openUrlTool && setFieldValue && (
                  <label className="flex items-center gap-2 cursor-pointer mt-1.5 ml-1">
                    <input
                      type="checkbox"
                      checked={enabledToolsMap[openUrlTool.id] || false}
                      onChange={(e) => {
                        if (!isOpenUrlForced) {
                          setFieldValue(
                            `enabled_tools_map.${openUrlTool.id}`,
                            e.target.checked
                          );
                        }
                      }}
                      disabled={isOpenUrlForced}
                      className="h-3.5 w-3.5 rounded border-border-medium disabled:opacity-50 disabled:cursor-not-allowed"
                    />
                    <span className="text-xs">
                      Enable Open URL
                      {isOpenUrlForced && (
                        <span className="text-text-500 ml-1">
                          (required for Web Search)
                        </span>
                      )}
                    </span>
                  </label>
                )}
              </div>
            </div>
          }
          direction="bottom"
        />
      </div>
      {!hideSearchTool && searchTool && (
        <BooleanFormField
          name={`enabled_tools_map.${searchTool.id}`}
          label={searchTool.display_name}
          subtext="Search through your organization's knowledge base and documents"
          disabled={searchToolDisabled}
          disabledTooltip={searchToolDisabledTooltip}
        />
      )}

      {webSearchTool && (
        <BooleanFormField
          name={`enabled_tools_map.${webSearchTool.id}`}
          label={webSearchTool.display_name}
          subtext="Access real-time information and search the web for up-to-date results"
          onChange={(checked) => {
            // When enabling Web Search, also enable OpenURL
            if (checked && openUrlTool && setFieldValue) {
              setFieldValue(`enabled_tools_map.${openUrlTool.id}`, true);
            }
          }}
        />
      )}

      {imageGenerationTool && (
        <BooleanFormField
          name={`enabled_tools_map.${imageGenerationTool.id}`}
          label={imageGenerationTool.display_name}
          subtext="Generate and manipulate images using AI-powered tools."
          disabled={imageGenerationDisabled}
          disabledTooltip={imageGenerationDisabledTooltip}
        />
      )}

      {pythonTool && (
        <BooleanFormField
          name={`enabled_tools_map.${pythonTool.id}`}
          label={pythonTool.display_name}
          subtext={
            "Execute Python code in a secure, isolated environment to " +
            "analyze data, create visualizations, and perform computations"
          }
        />
      )}

      {customTools.length > 0 && (
        <>
          <Text as="p" mainUiBody text04 className="mb-2">
            OpenAPI Actions
          </Text>
          <MemoizedToolList tools={customTools} />
        </>
      )}

      {Object.keys(mcpToolsByServer).length > 0 && (
        <>
          <Text as="p" mainUiBody text04 className="mb-2">
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
