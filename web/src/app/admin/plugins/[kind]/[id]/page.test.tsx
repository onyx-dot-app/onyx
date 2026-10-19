import Page from "@/app/admin/plugins/[kind]/[id]/page";

jest.mock("next/navigation", () => ({
  redirect: jest.fn((href: string) => {
    throw new Error(href);
  }),
}));

test.each([
  ["mcp", "7", "/admin/plugins?plugin=mcp%3A7&trigger_fetch=true"],
  ["openapi", "42", "/admin/plugins?plugin=openapi%3A42&trigger_fetch=true"],
  [
    "external-app",
    "3",
    "/admin/plugins?plugin=external-app%3A3&trigger_fetch=true",
  ],
])(
  "opens an old %s detail link once on the Plugins page",
  async (kind, id, href) => {
    await expect(
      Page({
        params: Promise.resolve({ kind, id }),
        searchParams: Promise.resolve({ trigger_fetch: "true" }),
      })
    ).rejects.toThrow(href);
  }
);

test.each([
  ["nope", "7"],
  ["mcp", "0"],
  ["openapi", "abc"],
])("sends a malformed %s/%s link to the Plugins list", async (kind, id) => {
  await expect(
    Page({
      params: Promise.resolve({ kind, id }),
      searchParams: Promise.resolve({}),
    })
  ).rejects.toThrow(/^\/admin\/plugins$/);
});
