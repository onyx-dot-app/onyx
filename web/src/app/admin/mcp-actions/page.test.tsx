import Page from "@/app/admin/mcp-actions/page";
import { redirect } from "next/navigation";

jest.mock("next/navigation", () => ({
  redirect: jest.fn((href: string) => {
    throw new Error(href);
  }),
}));

test("redirects an in-flight OAuth return to its canonical detail", async () => {
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
    "/admin/plugins/mcp/7?server_id=7&trigger_fetch=true&message=oauth_connected&tab=tools&tag=one&tag=two"
  );
  expect(redirect).toHaveBeenCalledWith(
    "/admin/plugins/mcp/7?server_id=7&trigger_fetch=true&message=oauth_connected&tab=tools&tag=one&tag=two"
  );
});
