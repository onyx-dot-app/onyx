import { test, expect } from "@chromatic-com/playwright";
import { loginAsRandomUser } from "../utils/auth";
import { sendMessage } from "../utils/chatActions";

test.describe("Message feedback thumbs controls", () => {
  test.beforeEach(async ({ page }) => {
    await page.context().clearCookies();
    await loginAsRandomUser(page);

    await page.goto("/chat");
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
    const likeButton = aiMessage.getByTestId("AIMessage/like-button");
    const dislikeButton = aiMessage.getByTestId("AIMessage/dislike-button");

    await expect(likeButton).toBeVisible({ timeout: 15000 });
    await expect(dislikeButton).toBeVisible();

    // Thumbs up submits positive feedback
    await Promise.all([
      page.waitForRequest("**/api/chat/create-chat-message-feedback"),
      likeButton.click(),
    ]);
    expect(createFeedbackRequests).toHaveLength(1);
    const likedRequest = createFeedbackRequests[0];
    expect(likedRequest?.is_positive).toBe(true);
    expect(likedRequest?.chat_message_id).toBeTruthy();

    // Clicking thumbs up again removes the feedback
    await Promise.all([
      page.waitForRequest("**/api/chat/remove-chat-message-feedback?*"),
      likeButton.click(),
    ]);
    expect(removeFeedbackRequests).toHaveLength(1);
    expect(removeFeedbackRequests[0]?.query.chat_message_id).toBe(
      String(likedRequest?.chat_message_id)
    );

    // Thumbs down opens the feedback modal and submits negative feedback
    await dislikeButton.click();
    const modalTitle = page.getByText("Provide Additional Feedback").first();
    await expect(modalTitle).toBeVisible({ timeout: 5000 });

    const feedbackInput = page.getByPlaceholder(
      /What did you .* about this response\?/i
    );
    await feedbackInput.fill("Response missed some details.");

    await Promise.all([
      page.waitForRequest("**/api/chat/create-chat-message-feedback"),
      page.getByRole("button", { name: "Submit" }).click(),
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
