import { test, expect, Browser } from "@playwright/test";
import { loginAs, loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { CHECKERED_PNG } from "@tests/e2e/fixtures/images";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

test.describe("Persona avatar", () => {
  test.describe.configure({ mode: "serial" });

  let agentId: number | null = null;
  const agentName = `E2E Avatar Agent ${Date.now()}`;

  test.afterAll(async ({ browser }: { browser: Browser }) => {
    if (agentId === null) return;
    const context = await browser.newContext({
      storageState: "admin_auth.json",
    });
    const page = await context.newPage();
    const cleanupClient = new OnyxApiClient(page.request);
    await cleanupClient.deleteAgent(agentId);
    await context.close();
  });

  test("uploads an avatar and serves the exact bytes back to the owner", async ({
    page,
  }) => {
    const uploadResp = await page.request.post(
      "/api/admin/persona/upload-image",
      {
        multipart: {
          file: {
            name: "avatar.png",
            mimeType: "image/png",
            buffer: CHECKERED_PNG,
          },
        },
      }
    );
    expect(uploadResp.ok()).toBeTruthy();
    const uploadJson = (await uploadResp.json()) as { file_id: string };
    const avatarFileId = uploadJson.file_id;
    expect(avatarFileId).toBeTruthy();

    const createResp = await page.request.post("/api/persona", {
      data: {
        name: agentName,
        description: "Persona used to verify avatar serving.",
        document_set_ids: [],
        is_public: true,
        tool_ids: [],
        uploaded_image_id: avatarFileId,
        system_prompt: "",
        task_prompt: "",
        datetime_aware: true,
      },
    });
    expect(createResp.ok()).toBeTruthy();
    const persona = (await createResp.json()) as { id: number };
    agentId = persona.id;

    const avatarResp = await page.request.get(`/api/persona/${agentId}/avatar`);
    expect(avatarResp.status()).toBe(200);
    expect(avatarResp.headers()["content-type"]).toContain("image/png");
    const servedBytes = await avatarResp.body();
    expect(servedBytes.toString("base64")).toBe(
      CHECKERED_PNG.toString("base64")
    );
  });

  test("returns 404 for a non-existent persona", async ({ page }) => {
    const resp = await page.request.get("/api/persona/99999999/avatar");
    expect(resp.status()).toBe(404);
  });

  test("returns 404 when a persona has no avatar configured", async ({
    page,
  }) => {
    // The default assistant (id=0) ships without an uploaded_image_id.
    const resp = await page.request.get("/api/persona/0/avatar");
    expect(resp.status()).toBe(404);
  });

  test("serves a public persona's avatar to other authenticated users", async ({
    page,
  }, testInfo) => {
    expect(agentId).not.toBeNull();
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const avatarResp = await page.request.get(`/api/persona/${agentId}/avatar`);
    expect(avatarResp.status()).toBe(200);
    const bytes = await avatarResp.body();
    expect(bytes.toString("base64")).toBe(CHECKERED_PNG.toString("base64"));

    // Re-auth as admin so afterAll cleanup uses the owner's session.
    await page.context().clearCookies();
    await loginAs(page, "admin");
  });

  test("renders the persona avatar in the chat UI", async ({ page }) => {
    expect(agentId).not.toBeNull();
    await page.goto(`/app?agentId=${agentId}`);
    await page.waitForLoadState("networkidle");

    const avatarImg = page
      .locator(`img[src="/api/persona/${agentId}/avatar"]`)
      .first();
    await expect(avatarImg).toBeVisible({ timeout: 10000 });

    // Capture the rendered avatar so we catch regressions in how the bytes
    // are decoded, cropped, and framed by the AgentAvatar component.
    const avatarContainer = avatarImg.locator("..");
    await expectElementScreenshot(avatarContainer, {
      name: "persona-avatar-chat",
    });
  });
});
