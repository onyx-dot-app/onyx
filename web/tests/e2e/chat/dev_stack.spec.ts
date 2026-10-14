import { expect, test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { loginAs } from "@tests/e2e/utils/auth";
import { MOCK_LLM_DEFAULT_RESPONSE } from "@tests/e2e/utils/mockLlm";

test("dev stack streams and persists a backend chat response", async ({
  page,
}) => {
  test.skip(
    !process.env.MOCK_LLM_SERVER_URL,
    "Requires the local scripted LLM server"
  );
  await loginAs(page, "admin");
  const chat = new ChatPage(page);
  await chat.goto();
  const message = `Dev stack integration proof ${Date.now()}`;
  const responsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      response.url().includes("/api/chat/send-chat-message")
  );
  await chat.inputBar.fill(message);
  await chat.inputBar.send();
  const response = await responsePromise;
  expect(response.ok()).toBe(true);
  expect(await response.finished()).toBeNull();
  await chat.expectHumanMessage(message);
  await expect(chat.aiMessage()).toContainText(MOCK_LLM_DEFAULT_RESPONSE);
  await expect(page).toHaveURL(/chatId=/);
  await page.reload();
  await chat.expectHumanMessage(message);
  await expect(chat.aiMessage()).toContainText(MOCK_LLM_DEFAULT_RESPONSE);
});
