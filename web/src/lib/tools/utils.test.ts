import {
  extractMethodSpecsFromDefinition,
  getAdminConfigureInfo,
} from "@/lib/tools/utils";
import type { ToolSnapshot } from "@/lib/tools/types";

const tool: ToolSnapshot = {
  id: 7,
  name: "openapi-tool",
  display_name: "OpenAPI tool",
  description: "A custom OpenAPI tool",
  definition: {},
  custom_headers: [],
  in_code_tool_id: null,
  passthrough_auth: false,
  enabled: true,
  chat_selectable: true,
  agent_creation_selectable: true,
  default_enabled: false,
};

test("opens the selected OpenAPI plugin modal from a tool configuration link", () => {
  expect(
    getAdminConfigureInfo(tool, { openapi: "Configure custom tool" })
  ).toEqual({
    href: "/admin/plugins?plugin=openapi%3A7",
    tooltip: "Configure custom tool",
  });
});

test("retains built-in tool configuration destinations", () => {
  expect(
    getAdminConfigureInfo(
      { ...tool, in_code_tool_id: "WebSearchTool" },
      { WebSearchTool: "Configure web search" }
    )
  ).toEqual({
    href: "/admin/web-search",
    tooltip: "Configure web search",
  });
});

test("does not mistake MCP tools for OpenAPI plugins", () => {
  expect(getAdminConfigureInfo({ ...tool, mcp_server_id: 7 }, {})).toBeNull();
});

test("extracts only supported operations with text names and summaries", () => {
  const operation = { operationId: "listItems", summary: "List items" };
  expect(
    extractMethodSpecsFromDefinition({
      paths: {
        "/items": {
          get: operation,
          parameters: [{ name: "filter" }],
          post: { operationId: 42, summary: "Invalid operation" },
          delete: { operationId: "deleteItems", description: {} },
        },
      },
    })
  ).toEqual([
    {
      name: "listItems",
      summary: "List items",
      path: "/items",
      method: "GET",
      spec: operation,
      custom_headers: [],
    },
  ]);
});
