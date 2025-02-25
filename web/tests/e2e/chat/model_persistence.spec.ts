import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import {
  sendMessage,
  verifyCurrentModel,
  switchModel,
} from "../utils/chatActions";

test("Model persistence across page refresh", async ({ page }) => {
  // Setup: Clear cookies and log in as a random user
  await page.context().clearCookies();
  await loginAsRandomUser(page);

  // Navigate to chat page
  await page.goto("http://localhost:3000/chat");
  await page.waitForSelector("#onyx-chat-input-textarea");

  // Step 1: Send initial message
  await sendMessage(page, "Initial message");

  // Step 2: Switch to a different model
  const targetModel = "GPT 4 Turbo"; // Using a model we know exists from llm_ordering.spec.ts
  await switchModel(page, targetModel);
  await verifyCurrentModel(page, targetModel);

  // Step 3: Send another message with new model
  await sendMessage(page, "Message after model switch");
  await verifyCurrentModel(page, targetModel);

  // Step 4: Refresh the page
  await page.reload();
  await page.waitForSelector("#onyx-chat-input-textarea");

  // Step 5: Verify model persists after refresh
  await verifyCurrentModel(page, targetModel);
});
