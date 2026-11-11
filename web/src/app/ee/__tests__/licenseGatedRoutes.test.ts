/** Paid admin pages reach the /ee tree, whose layout turns away a deployment
 * whose license does not cover EE features. A path missing from EE_ROUTES
 * would load without that check. */
import { NextRequest } from "next/server";
import { proxy } from "@/proxy";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME } from "@/lib/constants";

const APP_DOMAIN = "https://onyx.example.com";

describe("proxy rewrites paid admin pages to the /ee tree", () => {
  test.each(["/admin/scim", "/admin/service-accounts"])("%s", async (path) => {
    const res = await proxy(
      new NextRequest(`${APP_DOMAIN}${path}`, {
        headers: { cookie: `${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=session` },
      })
    );
    expect(res.headers.get("x-middleware-rewrite")).toBe(
      `${APP_DOMAIN}/ee${path}`
    );
  });
});
