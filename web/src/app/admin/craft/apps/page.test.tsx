import Page from "@/app/admin/craft/apps/page";

const mockRedirect = jest.fn((href: string) => {
  throw new Error(href);
});
jest.mock("next/navigation", () => ({
  redirect: (href: string) => mockRedirect(href),
}));

test.each([
  [{}, "/admin/plugins"],
  [{ editAppId: "7" }, "/admin/plugins?plugin=external-app%3A7"],
  [
    { configureAppId: "8", source: "skills" },
    "/admin/plugins?plugin=external-app%3A8&source=skills",
  ],
  [{ appId: "9" }, "/admin/plugins?plugin=external-app%3A9"],
  [{ editAppId: "invalid", tab: "mcp" }, "/admin/plugins"],
])("redirects legacy app links %j", async (query, href) => {
  await expect(Page({ searchParams: Promise.resolve(query) })).rejects.toThrow(
    href
  );
  expect(mockRedirect).toHaveBeenLastCalledWith(href);
});
