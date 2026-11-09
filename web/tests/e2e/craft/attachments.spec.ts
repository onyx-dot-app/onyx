import { expect, test, type APIResponse } from "@playwright/test";
import { CraftAttachmentsPage } from "@tests/e2e/pages/CraftAttachmentsPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type { Settings } from "@/lib/settings/types";

test("removing a Craft attachment keeps its stored file without reattaching on reload", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const settingsResponse: APIResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBe(true);
  const settings: Settings = await settingsResponse.json();
  test.skip(
    settings.onyx_craft_enabled !== true,
    "Onyx Craft is disabled in this environment"
  );
  const api: OnyxApiClient = new OnyxApiClient(page.request);
  const sessionId: string = await api.createCraftSession(
    "E2E attachment ownership"
  );
  const craft: CraftAttachmentsPage = new CraftAttachmentsPage(page);
  const name: string = "attachment-ownership.txt";
  const content: string =
    "This file remains available after removing its draft chip.";
  try {
    await craft.goto(sessionId);
    const path: string = await craft.attach(name, content);
    await craft.remove(name);
    await craft.expectStored(sessionId, path, content);
    await craft.reload();
    await craft.expectNotAttached(name);
    await craft.expectStored(sessionId, path, content);
  } finally {
    await api.deleteCraftSession(sessionId);
  }
});
