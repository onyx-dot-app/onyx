/**
 * E2E Test: Personal Access Token (PAT) Management
 * Tests complete user flow: login → create → authenticate → delete
 */
import { test, expect } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { PATManagementPage } from "@tests/e2e/pages/PATManagementPage";

const ME_URL = "http://localhost:3000/api/me";

test("PAT Complete Workflow", async ({ page }, testInfo) => {
  // Skip in admin project - we test with fresh user auth
  test.skip(
    testInfo.project.name === "admin",
    "Test requires clean user auth state"
  );

  await page.context().clearCookies();
  const { email } = await loginAsRandomUser(page);

  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  const pat = new PATManagementPage(page);
  await pat.goto();

  const tokenName = `E2E Test Token ${Date.now()}`;
  await pat.openCreateModal();
  await pat.fillName(tokenName);
  await pat.selectExpiration("7 days");
  await pat.submit();

  const tokenValue = await pat.waitForCreatedToken();
  expect(tokenValue).toContain("onyx_pat_");

  await page.context().grantPermissions(["clipboard-read", "clipboard-write"]);
  await pat.copyCreatedToken();
  await page.waitForTimeout(500);
  const clipboardText = await page.evaluate(() =>
    navigator.clipboard.readText()
  );
  expect(clipboardText).toBe(tokenValue);

  await pat.close();
  await pat.expectListed(tokenName);

  // The token authenticates as its owner (fresh context, no session cookies).
  const testContext = await page.context().browser()!.newContext();
  const apiResponse = await testContext.request.get(ME_URL, {
    headers: { Authorization: `Bearer ${tokenValue}` },
  });
  expect(apiResponse.ok()).toBeTruthy();
  expect((await apiResponse.json()).email).toBe(email);
  await testContext.close();

  await pat.revokeToken(tokenName);
  await pat.expectNotListed(tokenName);

  const revokedContext = await page.context().browser()!.newContext();
  const revokedResponse = await revokedContext.request.get(ME_URL, {
    headers: { Authorization: `Bearer ${tokenValue}` },
  });
  await revokedContext.close();
  expect(revokedResponse.status()).toBe(403);
});

test("PAT Multiple Tokens Management", async ({ page }, testInfo) => {
  // Skip in admin project - we test with fresh user auth
  test.skip(
    testInfo.project.name === "admin",
    "Test requires clean user auth state"
  );

  await page.context().clearCookies();
  await loginAsRandomUser(page);

  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  const pat = new PATManagementPage(page);
  await pat.goto();

  const tokens = [
    { name: `Token 1 - ${Date.now()}`, expiration: "7 days" },
    { name: `Token 2 - ${Date.now() + 1}`, expiration: "30 days" },
    { name: `Token 3 - ${Date.now() + 2}`, expiration: "No expiration" },
  ];

  for (const token of tokens) {
    await pat.openCreateModal();
    await pat.fillName(token.name);
    await pat.selectExpiration(token.expiration);
    await pat.submit();
    await pat.waitForCreatedToken();
    await pat.close();
    await pat.expectListed(token.name);
  }

  for (const token of tokens) {
    await pat.expectListed(token.name);
  }

  await pat.revokeToken(tokens[1]!.name);
  await pat.expectNotListed(tokens[1]!.name);
  await pat.expectListed(tokens[0]!.name);
  await pat.expectListed(tokens[2]!.name);
});

test("PAT Scoped Token (limited access)", async ({ page }, testInfo) => {
  test.skip(
    testInfo.project.name === "admin",
    "Test requires clean user auth state"
  );

  await page.context().clearCookies();
  await loginAsRandomUser(page);

  await page.goto("/app");
  await page.waitForLoadState("networkidle");

  const pat = new PATManagementPage(page);
  await pat.goto();

  const tokenName = `Scoped Token ${Date.now()}`;
  await pat.openCreateModal();
  await pat.fillName(tokenName);
  await pat.chooseLimitedAccess();
  await pat.toggleScope("Search Read");
  await pat.submit();

  const tokenValue = await pat.waitForCreatedToken();
  await pat.close();

  await pat.expectRowText(/Created today.*Read search/);

  // The scoped token reaches the scope-exempt /me but is denied on a
  // BASIC_ACCESS route, proving the UI actually scoped it (not full access).
  const ctx = await page.context().browser()!.newContext();
  const meResponse = await ctx.request.get(ME_URL, {
    headers: { Authorization: `Bearer ${tokenValue}` },
  });
  expect(meResponse.ok()).toBeTruthy();
  const patsResponse = await ctx.request.get(
    "http://localhost:3000/api/user/pats",
    { headers: { Authorization: `Bearer ${tokenValue}` } }
  );
  expect(patsResponse.status()).toBe(403);
  await ctx.close();
});
