import Page from "@/app/admin/openapi-actions/page";

jest.mock("next/navigation", () => ({
  redirect: jest.fn((href: string) => {
    throw new Error(href);
  }),
}));

test("redirects to the directory without dropping query values", async () => {
  await expect(
    Page({
      searchParams: Promise.resolve({ tab: "tools", tag: ["one", "two"] }),
    })
  ).rejects.toThrow("/admin/plugins?tab=tools&tag=one&tag=two");
});
