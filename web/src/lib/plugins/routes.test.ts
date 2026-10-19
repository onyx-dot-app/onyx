import {
  legacyMcpListHref,
  mcpOAuthReturnHref,
  OPEN_PLUGIN_PARAM,
  parsePluginId,
  parsePluginReference,
  pluginOpenHref,
  withPluginSearchParams,
} from "@/lib/plugins/routes";
import { ADMIN_ROUTES } from "@/lib/admin-routes";

describe("plugin routes", () => {
  test("qualifies equal numeric IDs by plugin kind", () => {
    expect(OPEN_PLUGIN_PARAM).toBe("plugin");
    expect(pluginOpenHref({ kind: "mcp", id: 7 })).toBe(
      "/admin/plugins?plugin=mcp%3A7"
    );
    expect(pluginOpenHref({ kind: "openapi", id: 7 })).toBe(
      "/admin/plugins?plugin=openapi%3A7"
    );
    expect(pluginOpenHref({ kind: "external-app", id: 7 })).toBe(
      "/admin/plugins?plugin=external-app%3A7"
    );
  });

  test("puts the plugin first and keeps other parameters", () => {
    expect(
      pluginOpenHref(
        { kind: "openapi", id: 7 },
        new URLSearchParams({ configure: "authentication" })
      )
    ).toBe("/admin/plugins?plugin=openapi%3A7&configure=authentication");
    expect(
      pluginOpenHref({ kind: "mcp", id: 7 }, { tag: ["one", "two"] })
    ).toBe("/admin/plugins?plugin=mcp%3A7&tag=one&tag=two");
  });

  test("returns from OAuth to the saved MCP modal with a one-time fetch", () => {
    expect(mcpOAuthReturnHref(7)).toBe(
      "/admin/plugins?plugin=mcp%3A7&trigger_fetch=true"
    );
  });
  test("preserves explicit chat enablement through OAuth", () => {
    expect(mcpOAuthReturnHref(7, true)).toBe(
      "/admin/plugins?plugin=mcp%3A7&trigger_fetch=true&enable_chat=true"
    );
  });
});

describe("plugin reference parsing", () => {
  test.each([
    ["mcp:7", { kind: "mcp", id: 7 }],
    ["openapi:0007", { kind: "openapi", id: 7 }],
    ["external-app:9", { kind: "external-app", id: 9 }],
  ])("reads %s", (value, reference) => {
    expect(parsePluginReference(value)).toEqual(reference);
  });

  test("reads the value a plugin link produces", () => {
    const href = pluginOpenHref({ kind: "external-app", id: 9 });
    const value = new URL(href, "http://localhost").searchParams.get(
      OPEN_PLUGIN_PARAM
    );
    expect(parsePluginReference(value)).toEqual({
      kind: "external-app",
      id: 9,
    });
  });

  test.each([
    null,
    "",
    "7",
    ":7",
    "mcp",
    "mcp:",
    "mcp:0",
    "mcp:7abc",
    "mcp:-7",
    "tool:7",
    "MCP:7",
    "mcp:7:8",
  ])("rejects %p", (value) => {
    expect(parsePluginReference(value)).toBeNull();
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
  test("opens the plugin's modal and keeps repeated query values", () => {
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
      "/admin/plugins?plugin=mcp%3A7&server_id=7&tab=authentication&trigger_fetch=true&message=oauth_connected&filter=one&filter=two"
    );
  });

  test("uses the first server ID without dropping repeated IDs", () => {
    expect(legacyMcpListHref({ server_id: ["7", "8"] })).toBe(
      "/admin/plugins?plugin=mcp%3A7&server_id=7&server_id=8"
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
