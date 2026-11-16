import { expect, test } from "@playwright/test";
import { CraftSkillNoticePage } from "@tests/e2e/pages/CraftSkillNoticePage";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import type { Settings } from "@/lib/settings/types";
import type { ApiDetailedSessionResponse } from "@/app/craft/types/streamingTypes";
import type { SkillLimitNotice } from "@/lib/skills/limits";

test.beforeEach(async ({ page }, testInfo) => {
  await page.context().clearCookies();
  await loginAsWorkerUser(page, testInfo.workerIndex);
  const settingsResponse = await page.request.get("/api/settings");
  expect(settingsResponse.ok()).toBe(true);
  const settings: Settings = await settingsResponse.json();
  test.skip(
    settings.onyx_craft_enabled !== true,
    "Onyx Craft is disabled in this environment"
  );
});

test("names the skills that did not load and hides them on dismiss", async ({
  page,
}) => {
  const api = new OnyxApiClient(page.request);
  const sessionId = await api.createCraftSession("E2E skill runtime notice");
  const notice: SkillLimitNotice = {
    skills: [
      {
        plugin_id: "00000000-0000-4000-8000-000000000041",
        name: "huge-dataset-skill",
        bytes: 950 * 1024 * 1024,
        files: 12,
        reason: "bytes",
      },
    ],
    max_bytes: 900 * 1024 * 1024,
    max_files: 10_000,
  };
  const session: ApiDetailedSessionResponse = {
    id: sessionId,
    user_id: null,
    name: "E2E skill runtime notice",
    status: "active",
    created_at: "2026-01-01T00:00:00Z",
    last_activity_at: "2026-01-01T00:00:00Z",
    nextjs_port: null,
    sandbox: {
      id: "00000000-0000-4000-8000-000000000042",
      status: "running",
      container_id: null,
      created_at: "2026-01-01T00:00:00Z",
      last_heartbeat: null,
    },
    artifacts: [],
    sharing_scope: "private",
    origin: "INTERACTIVE",
    agent_provider: null,
    agent_model: null,
    skills_stale: false,
    skill_omissions: notice,
    session_loaded_in_sandbox: true,
  };
  const sessionUrl = `**/api/build/sessions/${sessionId}`;
  await page.route(sessionUrl, (route) => route.fulfill({ json: session }));
  await page.route(`${sessionUrl}/sandbox-status`, (route) =>
    route.fulfill({
      json: { status: "running", skills_stale: false, skill_omissions: notice },
    })
  );
  await page.route(`${sessionUrl}/artifacts`, (route) =>
    route.fulfill({ json: [] })
  );
  await page.route(`${sessionUrl}/files*`, (route) =>
    route.fulfill({ json: { path: "", entries: [] } })
  );
  await page.route(`${sessionUrl}/messages`, (route) =>
    route.fulfill({ json: { messages: [] } })
  );
  await page.route(`${sessionUrl}/output-cards`, (route) =>
    route.fulfill({ json: { cards: [] } })
  );

  const chat = new CraftSkillNoticePage(page);
  await chat.outputs.goto(sessionId);

  await chat.expectNotice("1 skill did not load", "huge-dataset-skill");
  await chat.dismiss();
});
