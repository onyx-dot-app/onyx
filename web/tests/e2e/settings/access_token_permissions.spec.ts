import { expect, test } from "@playwright/test";
import * as yup from "yup";
import { SettingsAccessTokensPage } from "@tests/e2e/pages/SettingsAccessTokensPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import {
  TEST_ADMIN_CREDENTIALS,
  WORKER_USER_POOL_SIZE,
  workerUserCredentials,
} from "@tests/e2e/constants";

const userSchema = yup.object({ id: yup.string().required() }).required();

test("a full access token keeps its original permissions after promotion @exclusive", async ({
  page,
  browser,
}, testInfo) => {
  const baseURL = testInfo.project.use.baseURL;
  const adminContext = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  });
  const tokenContext = await browser.newContext({
    baseURL,
    storageState: { cookies: [], origins: [] },
  });
  const adminLogin = await adminContext.request.post("/api/auth/login", {
    form: {
      username: TEST_ADMIN_CREDENTIALS.email,
      password: TEST_ADMIN_CREDENTIALS.password,
    },
  });
  expect(adminLogin.status()).toBe(204);
  const credentials = workerUserCredentials(
    testInfo.workerIndex % WORKER_USER_POOL_SIZE
  );
  const tokenIds: number[] = [];
  let userId: string | undefined;
  let promoted = false;

  try {
    await page.context().clearCookies();
    const registration = await page.request.post("/api/auth/register", {
      data: { ...credentials, username: credentials.email },
    });
    if (registration.status() !== 201) {
      expect(await registration.text()).toContain(
        "REGISTER_USER_ALREADY_EXISTS"
      );
    }
    await loginAsWorkerUser(page, testInfo.workerIndex);
    const userResponse = await page.request.get("/api/me");
    expect(userResponse.status()).toBe(200);
    const userBody: unknown = await userResponse.json();
    const user = await userSchema.validate(userBody, { strict: true });
    userId = user.id;
    const initialAccess = await page.request.get("/api/manage/users/counts");
    expect(initialAccess.status()).toBe(403);

    const tokensPage = new SettingsAccessTokensPage(page);
    await tokensPage.goto();
    const originalToken =
      await tokensPage.createFullAccessToken("Before promotion");
    tokenIds.push(originalToken.id);

    const beforePromotion = await tokenContext.request.get(
      "/api/manage/users/counts",
      {
        headers: { Authorization: `Bearer ${originalToken.token}` },
      }
    );
    expect(beforePromotion.status()).toBe(403);

    const promotion = await adminContext.request.patch(
      "/api/manage/admin/users/admin-access",
      {
        data: { user_email: credentials.email, is_admin: true },
      }
    );
    expect(promotion.status()).toBe(200);
    promoted = true;
    await expect
      .poll(async () =>
        (await page.request.get("/api/manage/users/counts")).status()
      )
      .toBe(200);

    const afterPromotion = await tokenContext.request.get(
      "/api/manage/users/counts",
      {
        headers: { Authorization: `Bearer ${originalToken.token}` },
      }
    );
    expect(afterPromotion.status()).toBe(403);

    await tokensPage.goto();
    await tokensPage.expectListedScopes("Before promotion", "Full access");
    const promotedToken =
      await tokensPage.createFullAccessToken("After promotion");
    tokenIds.push(promotedToken.id);
    const newTokenAccess = await tokenContext.request.get(
      "/api/manage/users/counts",
      {
        headers: { Authorization: `Bearer ${promotedToken.token}` },
      }
    );
    expect(newTokenAccess.status()).toBe(200);
  } finally {
    try {
      try {
        for (const tokenId of tokenIds) {
          const response = await page.request.delete(
            `/api/user/pats/${tokenId}`
          );
          expect(response.status()).toBe(200);
        }
      } finally {
        if (promoted && userId) {
          const response = await adminContext.request.patch(
            "/api/manage/admin/users/admin-access",
            { data: { user_email: credentials.email, is_admin: false } }
          );
          expect(response.status()).toBe(200);
        }
      }
    } finally {
      await tokenContext.close();
      await adminContext.close();
    }
  }
});
