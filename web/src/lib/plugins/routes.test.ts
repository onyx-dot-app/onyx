import {
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

describe("query strings", () => {
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
