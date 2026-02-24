import { test, expect } from "@playwright/test";
import { loginAsRandomUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";

test.describe("Message feedback thumbs controls", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    await page.goto("/app");
    await page.waitForLoadState("networkidle");
  });

  test("allows submitting and clearing thumbs up/down feedback", async ({
    page,
  }) => {
    const createFeedbackRequests: {
      is_positive: boolean;
      chat_message_id: number;
      feedback_text?: string;
      predefined_feedback?: string;
    }[] = [];
    const removeFeedbackRequests: {
      url: string;
      query: Record<string, string>;
    }[] = [];

    await page.route(
      "**/api/chat/create-chat-message-feedback",
      async (route) => {
        const body = JSON.parse(route.request().postData() ?? "{}");
        createFeedbackRequests.push(body);
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "{}",
        });
      }
    );

    await page.route(
      "**/api/chat/remove-chat-message-feedback?*",
      async (route) => {
        const url = new URL(route.request().url());
        removeFeedbackRequests.push({
          url: route.request().url(),
          query: Object.fromEntries(url.searchParams.entries()),
        });
        await route.fulfill({
          status: 200,
          contentType: "application/json",
          body: "{}",
        });
      }
    );

    await sendMessage(page, "Share a short fun fact.");

    const aiMessage = page.getByTestId("onyx-ai-message").last();
    const likeButton = aiMessage.getByTestId("AgentMessage/like-button");
    const dislikeButton = aiMessage.getByTestId("AgentMessage/dislike-button");

    await expect(likeButton).toBeVisible({ timeout: 15000 });
    await expect(dislikeButton).toBeVisible();

    // Thumbs up opens the feedback modal with optional feedback
    await likeButton.click();
    const modalTitle = page.getByText("Feedback").first();
    await expect(modalTitle).toBeVisible({ timeout: 5000 });

    // Submit without entering feedback (optional for thumbs up)
    const submitButton = page.getByRole("button", { name: "Submit" });
    await expect(submitButton).toBeEnabled({ timeout: 2000 });

    await Promise.all([
      page.waitForRequest("**/api/chat/create-chat-message-feedback"),
      submitButton.click(),
    ]);

    expect(createFeedbackRequests).toHaveLength(1);
    const likedRequest = createFeedbackRequests[0];
    expect(likedRequest?.is_positive).toBe(true);
    expect(likedRequest?.chat_message_id).toBeTruthy();
    expect(likedRequest?.feedback_text).toBeFalsy();

    await expect(modalTitle).toBeHidden({ timeout: 5000 });

    // Clicking thumbs up again removes the feedback
    await Promise.all([
      page.waitForRequest("**/api/chat/remove-chat-message-feedback?*"),
      likeButton.click(),
    ]);
    expect(removeFeedbackRequests).toHaveLength(1);
    expect(removeFeedbackRequests[0]?.query.chat_message_id).toBe(
      String(likedRequest?.chat_message_id)
    );

    // Thumbs down opens the feedback modal with mandatory feedback
    await dislikeButton.click();
    await expect(modalTitle).toBeVisible({ timeout: 5000 });

    // Verify submit button is disabled without feedback
    const submitButtonDislike = page.getByRole("button", { name: "Submit" });
    await expect(submitButtonDislike).toBeDisabled();

    // Enter feedback (mandatory for thumbs down)
    const feedbackInput = page.getByPlaceholder(
      /What did you .* about this response\?/i
    );
    await feedbackInput.fill("Response missed some details.");

    // Submit button should now be enabled
    await expect(submitButtonDislike).toBeEnabled();

    await Promise.all([
      page.waitForRequest("**/api/chat/create-chat-message-feedback"),
      submitButtonDislike.click(),
    ]);

    expect(createFeedbackRequests).toHaveLength(2);
    const dislikedRequest = createFeedbackRequests[1];
    expect(dislikedRequest?.is_positive).toBe(false);
    expect(dislikedRequest?.feedback_text).toContain("missed some details");
    expect(dislikedRequest?.chat_message_id).toBe(
      likedRequest?.chat_message_id
    );

    await expect(modalTitle).toBeHidden({ timeout: 5000 });
  });
});
