import {
  legacyMcpListHref,
  mcpOAuthReturnHref,
  parsePluginId,
  pluginDetailHref,
  withPluginSearchParams,
} from "@/lib/plugins/routes";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

describe("plugin routes", () => {
  test("qualifies equal numeric IDs by plugin kind", () => {
    expect(pluginDetailHref({ kind: "mcp", id: 7 })).toBe(
      "/admin/plugins/mcp/7"
    );
    expect(pluginDetailHref({ kind: "openapi", id: 7 })).toBe(
      "/admin/plugins/openapi/7"
    );
  });

  test("returns from OAuth to the saved MCP detail with a one-time fetch", () => {
    expect(mcpOAuthReturnHref(7)).toBe(
      "/admin/plugins/mcp/7?trigger_fetch=true"
    );
  });
  test("preserves explicit chat enablement through OAuth", () => {
    expect(mcpOAuthReturnHref(7, true)).toBe(
      "/admin/plugins/mcp/7?trigger_fetch=true&enable_chat=true"
    );
  });
});

describe("route ID boundary", () => {
  test.each(["7", "0007", String(Number.MAX_SAFE_INTEGER)])(
    "accepts positive safe integer %s",
    (value) => {
      expect(parsePluginId(value)).toBe(Number(value));
    }
  );

  test.each([
    undefined,
    "",
    "0",
    "-7",
    "7.1",
    "7abc",
    "1e2",
    "0x7",
    "Infinity",
    "NaN",
    " 7",
    "9007199254740992",
  ])("rejects an invalid ID %s", (value) => {
    expect(parsePluginId(value)).toBeNull();
  });
});

describe("legacy query strings", () => {
  test("opens the canonical detail and keeps repeated query values", () => {
    expect(
      legacyMcpListHref({
        server_id: "7",
        tab: "authentication",
        trigger_fetch: "true",
        message: "oauth_connected",
        filter: ["one", "two"],
        missing: undefined,
      })
    ).toBe(
      "/admin/plugins/mcp/7?server_id=7&tab=authentication&trigger_fetch=true&message=oauth_connected&filter=one&filter=two"
    );
  });

  test("uses the first server ID without dropping repeated IDs", () => {
    expect(legacyMcpListHref({ server_id: ["7", "8"] })).toBe(
      "/admin/plugins/mcp/7?server_id=7&server_id=8"
    );
  });

  test.each(["0", "7invalid", "9007199254740992"])(
    "keeps invalid legacy ID %s on the directory query",
    (serverId) => {
      expect(legacyMcpListHref({ server_id: serverId, tab: "tools" })).toBe(
        `/admin/plugins?server_id=${serverId}&tab=tools`
      );
    }
  );

  test("redirects an empty legacy list to the directory", () => {
    expect(legacyMcpListHref({})).toBe("/admin/plugins");
  });

  test("keeps create intent and encodes the existing query", () => {
    expect(
      withPluginSearchParams(
        ADMIN_ROUTES.PLUGINS.path,
        {
          filter: ["team one", "a&b"],
          empty: "",
        },
        "add=mcp"
      )
    ).toBe("/admin/plugins?add=mcp&filter=team+one&filter=a%26b&empty=");
  });
});
