import { test } from "@playwright/test";
import { CraftAttachmentsPage } from "@tests/e2e/pages/CraftAttachmentsPage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test("removing a Craft attachment keeps its stored file without reattaching on reload", async ({
  page,
}, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const api = new OnyxApiClient(page.request);
  const sessionId = await api.createCraftSession("E2E attachment ownership");
  const craft = new CraftAttachmentsPage(page);
  const name = "attachment-ownership.txt";
  const content = "This file remains available after removing its draft chip.";
  try {
    await craft.goto(sessionId);
    const path = await craft.attach(name, content);
    await craft.remove(name);
    await craft.expectStored(sessionId, path, content);
    await craft.reload();
    await craft.expectNotAttached(name);
    await craft.expectStored(sessionId, path, content);
  } finally {
    await api.deleteCraftSession(sessionId);
  }
});
