import { test, expect } from "@playwright/test";
import { SERVER_SIDE_ONLY__AUTH_COOKIE_NAME as AUTH_COOKIE_NAME } from "@/lib/constants";
import { LoginPage } from "@tests/e2e/pages/LoginPage";

// A session cookie the backend has no record of, for example one set by
// another stack on the same host, or one whose Redis key was dropped.
test.describe("Unknown session cookie", () => {
  test("lands on the login page and the cookie is cleared", async ({
    page,
    baseURL,
  }) => {
    const context = page.context();
    await context.clearCookies();
    await context.addCookies([
      {
        name: AUTH_COOKIE_NAME,
        value: "unknown-session-token",
        url: baseURL ?? "http://localhost:3000",
      },
    ]);

    const loginPage = new LoginPage(page);
    await loginPage.gotoAppRoot();

    await loginPage.expectVisible();
    await expect
      .poll(async () =>
        (await context.cookies()).some(
          (cookie) => cookie.name === AUTH_COOKIE_NAME
        )
      )
      .toBe(false);

    // The login page stays put once the cookie is gone.
    await loginPage.reload();
    await loginPage.expectVisible();
  });
});
