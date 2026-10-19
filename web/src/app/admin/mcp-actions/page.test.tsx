import Page from "@/app/admin/mcp-actions/page";
import { redirect } from "next/navigation";

jest.mock("next/navigation", () => ({
  redirect: jest.fn((href: string) => {
    throw new Error(href);
  }),
}));

test("redirects an in-flight OAuth return to its plugin modal", async () => {
  await expect(
    Page({
      searchParams: Promise.resolve({
        server_id: "7",
        trigger_fetch: "true",
        message: "oauth_connected",
        tab: "tools",
        tag: ["one", "two"],
      }),
    })
  ).rejects.toThrow(
    "/admin/plugins?plugin=mcp%3A7&server_id=7&trigger_fetch=true&message=oauth_connected&tab=tools&tag=one&tag=two"
  );
  expect(redirect).toHaveBeenCalledWith(
    "/admin/plugins?plugin=mcp%3A7&server_id=7&trigger_fetch=true&message=oauth_connected&tab=tools&tag=one&tag=two"
  );
});
