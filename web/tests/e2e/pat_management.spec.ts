/**
 * E2E Test: Personal Access Token (PAT) Management
 * Tests complete user flow: login → create → authenticate → delete
 */
import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "./utils/auth";

test("PAT Complete Workflow", async ({ page }) => {
  await page.context().clearCookies();
  const { email } = await loginAsRandomUser(page);

  await page.goto("http://localhost:3000/chat");
  await page.waitForLoadState("networkidle");

  const settingsButton = page.locator('[data-testid="user-settings-button"]');
  if (await settingsButton.isVisible()) {
    await settingsButton.click();
  } else {
    const profileButton = page
      .locator("button")
      .filter({ hasText: email })
      .first();
    if (await profileButton.isVisible()) {
      await profileButton.click();
    } else {
      const settingsAria = page
        .locator('button[aria-label*="Settings"]')
        .first();
      await settingsAria.click();
    }
  }

  await expect(
    page.locator("text=User Settings").or(page.locator("text=Settings"))
  ).toBeVisible({
    timeout: 5000,
  });

  const accessTokensTab = page
    .locator("text=Access Tokens")
    .or(page.locator('button:has-text("Access Tokens")'))
    .first();
  await accessTokensTab.click();

  await expect(
    page
      .locator("text=Create New Token")
      .or(page.locator("text=Personal Access Tokens"))
  ).toBeVisible({
    timeout: 5000,
  });

  const tokenName = `E2E Test Token ${Date.now()}`;
  const nameInput = page
    .locator('input[placeholder*="name" i]')
    .or(page.locator('input[name="name"]'))
    .first();
  await nameInput.fill(tokenName);

  const expirationSelect = page
    .locator("select")
    .filter({ has: page.locator('option:has-text("7 days")') })
    .first();
  if (await expirationSelect.isVisible()) {
    await expirationSelect.selectOption({ label: "7 days" });
  }

  const createButton = page.locator('button:has-text("Create")').first();
  await createButton.click();

  await expect(page.locator(`text=${tokenName}`)).toBeVisible({
    timeout: 5000,
  });

  const tokenDisplay = page
    .locator('[data-testid="token-value"]')
    .or(page.locator("code").filter({ hasText: "onyx_pat_" }))
    .first();
  await tokenDisplay.waitFor({ state: "visible", timeout: 5000 });

  const tokenValue = await tokenDisplay.textContent();
  expect(tokenValue).toContain("onyx_pat_");

  const copyButton = page
    .locator('button[aria-label*="Copy" i]')
    .or(page.locator('button:has-text("Copy")'))
    .first();

  if (await copyButton.isVisible()) {
    await copyButton.click();
    await expect(
      page
        .locator("text=Copied")
        .or(page.locator('[data-testid="copy-success"]'))
    ).toBeVisible({ timeout: 2000 });
  }

  const apiResponse = await page.request.get("http://localhost:3000/api/me", {
    headers: {
      Authorization: `Bearer ${tokenValue}`,
    },
  });
  expect(apiResponse.ok()).toBeTruthy();
  const userData = await apiResponse.json();
  expect(userData.email).toBe(email);

  const tokenRow = page
    .locator(`[data-testid="token-row"]`)
    .filter({ hasText: tokenName });
  const deleteButton = tokenRow
    .locator('button[aria-label*="Delete" i]')
    .or(tokenRow.locator("button").filter({ has: page.locator("svg") }))
    .first();
  await deleteButton.click();

  const confirmButton = page
    .locator('button:has-text("Delete")')
    .or(page.locator('button:has-text("Confirm")'))
    .last();
  await confirmButton.waitFor({ state: "visible", timeout: 3000 });
  await confirmButton.click();

  await expect(page.locator(`text=${tokenName}`)).not.toBeVisible({
    timeout: 5000,
  });

  const revokedApiResponse = await page.request.get(
    "http://localhost:3000/api/me",
    {
      headers: {
        Authorization: `Bearer ${tokenValue}`,
      },
    }
  );
  expect(revokedApiResponse.status()).toBe(401);
});

test("PAT Multiple Tokens Management", async ({ page }) => {
  await page.context().clearCookies();
  const { email } = await loginAsRandomUser(page);

  await page.goto("http://localhost:3000/chat");
  await page.waitForLoadState("networkidle");

  const settingsButton = page.locator('[data-testid="user-settings-button"]');
  if (await settingsButton.isVisible()) {
    await settingsButton.click();
  } else {
    const profileButton = page
      .locator("button")
      .filter({ hasText: email })
      .first();
    await profileButton.click();
  }

  await expect(
    page.locator("text=User Settings").or(page.locator("text=Settings"))
  ).toBeVisible({
    timeout: 5000,
  });

  const accessTokensTab = page
    .locator("text=Access Tokens")
    .or(page.locator('button:has-text("Access Tokens")'))
    .first();
  await accessTokensTab.click();

  const tokens = [
    { name: `Token 1 - ${Date.now()}`, expiration: "7 days" },
    { name: `Token 2 - ${Date.now() + 1}`, expiration: "30 days" },
    { name: `Token 3 - ${Date.now() + 2}`, expiration: "No expiration" },
  ];

  for (const token of tokens) {
    const nameInput = page
      .locator('input[placeholder*="name" i]')
      .or(page.locator('input[name="name"]'))
      .first();
    await nameInput.fill(token.name);

    const expirationSelect = page.locator("select").first();
    if (await expirationSelect.isVisible()) {
      await expirationSelect.selectOption({ label: token.expiration });
    }

    const createButton = page.locator('button:has-text("Create")').first();
    await createButton.click();

    await expect(page.locator(`text=${token.name}`)).toBeVisible({
      timeout: 5000,
    });
    await page.waitForTimeout(500);
  }

  for (const token of tokens) {
    await expect(page.locator(`text=${token.name}`)).toBeVisible();
  }

  const tokenList = page
    .locator('[data-testid="token-row"]')
    .or(
      page
        .locator("div")
        .filter({ has: page.locator('button[aria-label*="Delete"]') })
    );
  const firstToken = tokenList.first();
  await expect(firstToken).toContainText(tokens[2]!.name);

  const token2Row = page
    .locator(`[data-testid="token-row"]`)
    .filter({ hasText: tokens[1]!.name });
  const deleteButton = token2Row
    .locator('button[aria-label*="Delete" i]')
    .or(token2Row.locator("button").filter({ has: page.locator("svg") }))
    .first();
  await deleteButton.click();

  const confirmButton = page
    .locator('button:has-text("Delete")')
    .or(page.locator('button:has-text("Confirm")'))
    .last();
  await confirmButton.waitFor({ state: "visible", timeout: 3000 });
  await confirmButton.click();

  await expect(page.locator(`text=${tokens[1]!.name}`)).not.toBeVisible({
    timeout: 5000,
  });

  await expect(page.locator(`text=${tokens[0]!.name}`)).toBeVisible();
  await expect(page.locator(`text=${tokens[2]!.name}`)).toBeVisible();
});
