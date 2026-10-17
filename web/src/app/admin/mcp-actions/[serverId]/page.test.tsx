import Page from "@/app/admin/mcp-actions/[serverId]/page";

jest.mock("next/navigation", () => ({
  redirect: jest.fn((href: string) => {
    throw new Error(href);
  }),
  notFound: jest.fn(() => {
    throw new Error("NOT_FOUND");
  }),
}));

test("redirects a legacy detail with its complete query", async () => {
  await expect(
    Page({
      params: Promise.resolve({ serverId: "7" }),
      searchParams: Promise.resolve({
        tab: "authentication",
        trigger_fetch: "true",
        message: "oauth_connected",
        tag: ["one", "two"],
      }),
    })
  ).rejects.toThrow(
    "/admin/plugins/mcp/7?tab=authentication&trigger_fetch=true&message=oauth_connected&tag=one&tag=two"
  );
});

test.each(["0", "bad", "9007199254740992"])(
  "rejects invalid detail ID %s before redirecting",
  async (serverId) => {
    await expect(
      Page({
        params: Promise.resolve({ serverId }),
        searchParams: Promise.resolve({ trigger_fetch: "true" }),
      })
    ).rejects.toThrow("NOT_FOUND");
  }
);
