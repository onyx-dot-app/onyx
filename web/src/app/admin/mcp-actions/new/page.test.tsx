import Page from "@/app/admin/mcp-actions/new/page";

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  redirect: jest.fn((href: string) => {
    throw new Error(href);
  }),
}));

test("opens MCP setup in the plugin directory with the existing query", async () => {
  await expect(
    Page({ searchParams: Promise.resolve({ tag: ["one", "two"] }) })
  ).rejects.toThrow("/admin/plugins?add=mcp&tag=one&tag=two");
});
