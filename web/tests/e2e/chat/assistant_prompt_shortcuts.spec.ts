import { expect, test } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";

test.describe("Assistant prompt shortcuts", () => {
  test("shows grouped shortcuts and keyboard selection follows visual order", async ({
    page,
  }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);

    const onyxApiClient = new OnyxApiClient(page.request);

    const createAgentResponse = await page.request.post("/api/persona", {
      data: {
        name: `Shortcut Agent ${Date.now()}`,
        description: "E2E assistant prompt shortcut test",
        document_set_ids: [],
        is_public: true,
        llm_model_provider_override: null,
        llm_model_version_override: null,
        starter_messages: null,
        users: [],
        groups: [],
        tool_ids: [],
        remove_image: false,
        uploaded_image_id: null,
        icon_name: null,
        search_start_date: null,
        label_ids: null,
        featured: false,
        display_priority: null,
        user_file_ids: [],
        hierarchy_node_ids: [],
        document_ids: [],
        system_prompt: "",
        replace_base_system_prompt: false,
        task_prompt: "",
        datetime_aware: false,
      },
    });
    expect(createAgentResponse.ok()).toBeTruthy();
    const agent = await createAgentResponse.json();
    const shortcutCommand = `collision_${Date.now()}`;

    try {
      const createUserShortcut = await page.request.post("/api/input_prompt", {
        data: {
          prompt: shortcutCommand,
          content: "user shortcut content",
          active: true,
          is_public: false,
        },
      });
      expect(createUserShortcut.ok()).toBeTruthy();

      const createAgentShortcut = await page.request.post(
        `/api/persona/${agent.id}/input_prompt`,
        {
          data: {
            prompt: shortcutCommand,
            content: "agent shortcut content",
            active: true,
          },
        }
      );
      expect(createAgentShortcut.ok()).toBeTruthy();

      const createInactiveAgentShortcut = await page.request.post(
        `/api/persona/${agent.id}/input_prompt`,
        {
          data: {
            prompt: `inactive_${Date.now()}`,
            content: "should not show",
            active: false,
          },
        }
      );
      expect(createInactiveAgentShortcut.ok()).toBeTruthy();

      await page.goto(`/app?agentId=${agent.id}`);
      await page.waitForSelector("#onyx-chat-input-textarea");

      const input = page.locator("#onyx-chat-input-textarea");
      await input.fill(`/${shortcutCommand}`);

      await expect(page.getByText("Agent Shortcuts")).toBeVisible();
      await expect(page.getByText("Your Shortcuts")).toBeVisible();
      await expect(page.getByText(shortcutCommand)).toHaveCount(2);
      await expect(page.getByText("should not show")).toHaveCount(0);

      await input.fill(`/${shortcutCommand}`);
      await input.press("Enter");
      await expect(input).toHaveValue("agent shortcut content");
    } finally {
      await onyxApiClient.deleteAgent(agent.id);
    }
  });
});
