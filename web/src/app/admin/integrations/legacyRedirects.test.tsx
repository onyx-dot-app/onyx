import McpActionsPage from "@/app/admin/mcp-actions/page";
import McpActionsNewPage from "@/app/admin/mcp-actions/new/page";
import McpActionsDetailPage from "@/app/admin/mcp-actions/[serverId]/page";
import OpenApiActionsPage from "@/app/admin/openapi-actions/page";
import PluginMcpPage from "@/app/admin/plugins/mcp/[serverId]/page";
import PluginOpenApiPage from "@/app/admin/plugins/openapi/[toolId]/page";
import PluginExternalAppPage from "@/app/admin/plugins/external-app/[appId]/page";
import CraftAppsPage from "@/app/admin/craft/apps/page";

const mockRedirect = jest.fn((href: string) => {
  throw new Error(href);
});
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  redirect: (href: string) => mockRedirect(href),
}));

test.each([
  ["/admin/mcp-actions", McpActionsPage],
  ["/admin/mcp-actions/new", McpActionsNewPage],
  ["/admin/mcp-actions/7", McpActionsDetailPage],
  ["/admin/openapi-actions", OpenApiActionsPage],
  ["/admin/plugins/mcp/7", PluginMcpPage],
  ["/admin/plugins/openapi/7", PluginOpenApiPage],
  ["/admin/plugins/external-app/7", PluginExternalAppPage],
  ["/admin/craft/apps", CraftAppsPage],
])("%s opens the integration list", (_path, Page) => {
  expect(() => Page()).toThrow("/admin/integrations");
  expect(mockRedirect).toHaveBeenLastCalledWith("/admin/integrations");
});
