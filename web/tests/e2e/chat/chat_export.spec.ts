// A chat downloads as a transcript from the header's share menu and from the
// chat's options menu in the sidebar.
import { readFile } from "node:fs/promises";
import { test, expect } from "@playwright/test";
import type { Download } from "@playwright/test";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { OnyxApiClient } from "@tests/e2e/utils/onyxApiClient";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import { mockLlmNonce } from "@tests/e2e/utils/mockLlm";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { AppSidebarPage } from "@tests/e2e/pages/AppSidebarPage";

const CHAT_NAME = "E2E Export Target";

async function downloadedText(download: Download): Promise<string> {
  return readFile(await download.path(), "utf8");
}

test.describe("Chat export", () => {
  let chatId: string;

  test.beforeEach(async ({ page }, testInfo) => {
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
    chatId = await new OnyxApiClient(page.request).createChatSession(CHAT_NAME);
  });

  test.afterEach(async ({ page }) => {
    await new OnyxApiClient(page.request).deleteChatSession(chatId);
  });

  test("the header share menu exports the chat as Markdown", async ({
    page,
  }) => {
    const chatPage = new ChatPage(page);
    await chatPage.goto(chatId);
    const question = `Export this question. ${mockLlmNonce()}`;
    await sendMessage(page, question);

    const download = await chatPage.exportFromShareMenu("Markdown");

    expect(download.suggestedFilename()).toBe("E2E_Export_Target.md");
    const transcript = await downloadedText(download);
    expect(transcript).toContain(`# ${CHAT_NAME}`);
    expect(transcript).toContain(`## User\n\n${question}`);
    expect(transcript).toContain("## Assistant\n\n");
  });

  test("the sidebar chat menu exports the chat as plain text", async ({
    page,
  }) => {
    const sidebar = new AppSidebarPage(page);
    await sidebar.goto();

    const download = await sidebar.chatRow(CHAT_NAME).exportAs("Plain Text");

    expect(download.suggestedFilename()).toBe("E2E_Export_Target.txt");
    expect(await downloadedText(download)).toBe(`${CHAT_NAME}\n`);
  });
});
