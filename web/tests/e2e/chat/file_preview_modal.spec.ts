import { test, expect, Page } from "@playwright/test";
import { loginAsRandomUser } from "../utils/auth";

/**
 * Builds a newline-delimited JSON stream body matching the packet
 * format that useChatController expects:
 *
 * 1. MessageResponseIDInfo — identifies the user/assistant messages
 * 2. Packet-wrapped streaming objects ({placement, obj}) — the actual content
 * 3. BackendMessage — the final completed message
 *
 * Each line is a raw JSON object parsed by handleSSEStream.
 */
function buildMockStream(messageContent: string): string {
  const packets = [
    // 1. Message ID info — tells the frontend the message IDs
    JSON.stringify({
      user_message_id: 1,
      reserved_assistant_message_id: 2,
    }),
    // 2. Streaming content packets wrapped in {placement, obj}
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "message_start",
        id: "mock-message-id",
        content: "",
        final_documents: null,
      },
    }),
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "message_delta",
        content: messageContent,
      },
    }),
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "message_end",
      },
    }),
    JSON.stringify({
      placement: { turn_index: 0 },
      obj: {
        type: "stop",
        stop_reason: "finished",
      },
    }),
    // 3. Final BackendMessage — the completed message record
    JSON.stringify({
      message_id: 2,
      message_type: "assistant",
      research_type: null,
      parent_message: 1,
      latest_child_message: null,
      message: messageContent,
      rephrased_query: null,
      context_docs: null,
      time_sent: new Date().toISOString(),
      citations: {},
      files: [],
      tool_call: null,
      overridden_model: null,
    }),
  ];
  return packets.join("\n") + "\n";
}

/**
 * Sends a message while intercepting the backend response with
 * a controlled mock stream. Returns once the AI message renders.
 */
async function sendMessageWithMockResponse(
  page: Page,
  userMessage: string,
  mockResponseContent: string
) {
  const existingMessageCount = await page
    .locator('[data-testid="onyx-ai-message"]')
    .count();

  // Intercept the send-chat-message endpoint and return our mock stream
  await page.route("**/api/chat/send-chat-message", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: buildMockStream(mockResponseContent),
    });
  });

  await page.locator("#onyx-chat-input-textarea").click();
  await page.locator("#onyx-chat-input-textarea").fill(userMessage);
  await page.locator("#onyx-chat-input-send-button").click();

  // Wait for the AI message to appear
  await expect(page.locator('[data-testid="onyx-ai-message"]')).toHaveCount(
    existingMessageCount + 1,
    { timeout: 30000 }
  );

  // Unroute so future requests go through normally
  await page.unroute("**/api/chat/send-chat-message");
}

const MOCK_FILE_ID = "00000000-0000-0000-0000-000000000001";

test.describe("File preview modal from chat file links", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);
    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  test("clicking a text file link opens the TextViewModal", async ({
    page,
  }) => {
    const mockContent = `Here is your file: [notes.txt](/api/chat/file/${MOCK_FILE_ID})`;

    // Mock the file endpoint to return text content
    await page.route(`**/api/chat/file/${MOCK_FILE_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/plain",
        body: "Hello from the mock file!",
      });
    });

    await sendMessageWithMockResponse(page, "Give me the file", mockContent);

    // Find the link in the AI message and click it
    const aiMessage = page.getByTestId("onyx-ai-message").last();
    const fileLink = aiMessage.locator("a").filter({ hasText: "notes.txt" });
    await expect(fileLink).toBeVisible({ timeout: 5000 });
    await fileLink.click();

    // Verify the modal opens
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Verify the file name is shown in the header
    await expect(modal.getByText("notes.txt")).toBeVisible();

    // Verify the download button exists
    await expect(modal.getByText("Download File")).toBeVisible();

    // Verify the file content is rendered
    await expect(modal.getByText("Hello from the mock file!")).toBeVisible();
  });

  test("clicking a code file link opens the CodeViewModal with syntax highlighting", async ({
    page,
  }) => {
    const mockContent = `Here is your script: [app.py](/api/chat/file/${MOCK_FILE_ID})`;
    const pythonCode = 'def hello():\n    print("Hello, world!")';

    // Mock the file endpoint to return Python code
    await page.route(`**/api/chat/file/${MOCK_FILE_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        body: pythonCode,
      });
    });

    await sendMessageWithMockResponse(page, "Give me the script", mockContent);

    // Find the link in the AI message and click it
    const aiMessage = page.getByTestId("onyx-ai-message").last();
    const fileLink = aiMessage.locator("a").filter({ hasText: "app.py" });
    await expect(fileLink).toBeVisible({ timeout: 5000 });
    await fileLink.click();

    // Verify the CodeViewModal opens
    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Verify the file name is shown in the header
    await expect(modal.getByText("app.py")).toBeVisible();

    // Verify the header description shows language and line info
    await expect(modal.getByText(/python/i)).toBeVisible();
    await expect(modal.getByText("2 lines", { exact: true })).toBeVisible();

    // Verify the code content is rendered
    await expect(modal.getByText("Hello, world!")).toBeVisible();

    // Verify the download icon button exists (tooltip-only, no visible text)
    const downloadButton = modal.locator("button").last();
    await expect(downloadButton).toBeVisible();

    // Hover to verify the download tooltip appears
    await downloadButton.hover();
    await expect(page.getByText("Download")).toBeVisible({ timeout: 3000 });
  });

  test("download button triggers file download", async ({ page }) => {
    const mockContent = `Here: [data.csv](/api/chat/file/${MOCK_FILE_ID})`;

    await page.route(`**/api/chat/file/${MOCK_FILE_ID}`, async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/csv",
        body: "name,age\nAlice,30\nBob,25",
      });
    });

    await sendMessageWithMockResponse(page, "Give me the csv", mockContent);

    const aiMessage = page.getByTestId("onyx-ai-message").last();
    const fileLink = aiMessage.locator("a").filter({ hasText: "data.csv" });
    await expect(fileLink).toBeVisible({ timeout: 5000 });
    await fileLink.click();

    const modal = page.getByRole("dialog");
    await expect(modal).toBeVisible({ timeout: 5000 });

    // Click the download button and verify a download starts
    const downloadPromise = page.waitForEvent("download");
    await modal.getByText("Download File").last().click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toContain("data.csv");
  });
});
