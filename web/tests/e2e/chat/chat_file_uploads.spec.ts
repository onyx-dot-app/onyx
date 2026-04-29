import { expect, Page, test } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
import { CHECKERED_PNG } from "@tests/e2e/fixtures/images";
import { loginAsWorkerUser } from "@tests/e2e/utils/auth";
import { sendMessage } from "@tests/e2e/utils/chatActions";
import {
  buildMockImageGenStream,
  buildMockStream,
  mockChatEndpoint,
  resetTurnCounter,
} from "@tests/e2e/utils/chatMock";
import { expectElementScreenshot } from "@tests/e2e/utils/visualRegression";

const SHORT_AI_RESPONSE = "I've reviewed the file you uploaded.";
const IMAGE_GEN_AI_MESSAGE = "Here is the image I generated for you.";

const PYTHON_CODE = `def greet(name: str) -> str:
    return f"Hello, {name}!"


if __name__ == "__main__":
    print(greet("Onyx"))
`;

interface UploadFile {
  name: string;
  mimeType: string;
  buffer: Buffer;
}

/**
 * Uploads one or more files via the hidden chat-input file picker and
 * waits for the upload request to return plus the file card(s) to render.
 *
 * `ImageFileCard` renders only a thumbnail `<img alt={filename}>` with no
 * visible text, so images are located by `img[alt=...]`; non-image cards
 * render the filename as visible text.
 */
async function uploadFilesToChat(
  page: Page,
  files: UploadFile[]
): Promise<void> {
  const fileInput = page.locator('input[type="file"]').first();
  const chooserPromise = page.waitForEvent("filechooser");
  await fileInput.dispatchEvent("click");
  const chooser = await chooserPromise;

  const uploadResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/api/user/projects/file/upload") &&
      response.request().method() === "POST"
  );

  await chooser.setFiles(files);

  const uploadResponse = await uploadResponsePromise;
  expect(uploadResponse.ok()).toBeTruthy();

  await page.waitForLoadState("networkidle");
  const inputWrapper = page.locator("#onyx-chat-input");
  for (const file of files) {
    const card = file.mimeType.startsWith("image/")
      ? inputWrapper.locator(`img[alt="${file.name}"]`)
      : inputWrapper.getByText(file.name);
    await expect(card.first()).toBeVisible({ timeout: 10000 });
  }
}

test.describe("Chat File Uploads", () => {
  let chat: ChatPage;

  test.beforeEach(async ({ page }, testInfo) => {
    resetTurnCounter();
    chat = new ChatPage(page);
    await page.context().clearCookies();
    await loginAsWorkerUser(page, testInfo.workerIndex);
  });

  test.describe("User-Uploaded Files", () => {
    test("uploaded text file renders in user message", async ({ page }) => {
      await chat.goto();
      await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

      const fileName = "notes-rendering.txt";
      await uploadFilesToChat(page, [
        {
          name: fileName,
          mimeType: "text/plain",
          buffer: Buffer.from(
            "Some notes about the upcoming Q3 roadmap.",
            "utf-8"
          ),
        },
      ]);

      await sendMessage(page, "Summarize this file");

      const userMessage = page.locator("#onyx-human-message").first();
      const fileDisplay = userMessage.locator("#onyx-file");
      await expect(fileDisplay).toBeVisible();
      await expect(fileDisplay.getByText(fileName)).toBeVisible();

      await chat.screenshotContainer("chat-uploaded-text-file");
    });

    test("uploaded image renders in user message", async ({ page }) => {
      await chat.goto();
      await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

      const fileName = "diagram-rendering.png";
      await uploadFilesToChat(page, [
        {
          name: fileName,
          mimeType: "image/png",
          buffer: CHECKERED_PNG,
        },
      ]);

      await sendMessage(page, "What's in this image?");

      const userMessage = page.locator("#onyx-human-message").first();
      const imageDisplay = userMessage.locator("#onyx-image");
      await expect(imageDisplay).toBeVisible();
      await expect(imageDisplay.locator("img").first()).toBeVisible();

      await chat.screenshotContainer("chat-uploaded-image");
    });

    test("multiple uploaded files render together", async ({ page }) => {
      await chat.goto();
      await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

      const textName = "notes-multi.txt";
      const imageName = "diagram-multi.png";
      await uploadFilesToChat(page, [
        {
          name: textName,
          mimeType: "text/plain",
          buffer: Buffer.from("Multi-file upload notes.", "utf-8"),
        },
        {
          name: imageName,
          mimeType: "image/png",
          buffer: CHECKERED_PNG,
        },
      ]);

      await sendMessage(page, "Look at both of these");

      const userMessage = page.locator("#onyx-human-message").first();
      await expect(
        userMessage.locator("#onyx-file").getByText(textName)
      ).toBeVisible();
      await expect(
        userMessage.locator("#onyx-image").locator("img").first()
      ).toBeVisible();

      await chat.screenshotContainer("chat-uploaded-multiple-files");
    });
  });

  test.describe("LLM-Generated Images", () => {
    test("AI response with generated image renders correctly", async ({
      page,
    }) => {
      await chat.goto();

      const fileId = "00000000-0000-0000-0000-00000000aaaa";

      await page.route(`**/api/chat/file/${fileId}`, async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "image/png",
          body: CHECKERED_PNG,
        });
      });

      await mockChatEndpoint(
        page,
        buildMockImageGenStream({
          fileId,
          revisedPrompt: "A friendly cartoon onyx stone with a smile",
          message: IMAGE_GEN_AI_MESSAGE,
        })
      );

      await sendMessage(
        page,
        "Generate an image of a friendly cartoon onyx stone"
      );

      const aiMessage = page.getByTestId("onyx-ai-message").first();
      const generatedImage = aiMessage.locator('img[alt="Chat Message Image"]');
      await expect(generatedImage).toBeVisible({ timeout: 10000 });
      await expect(generatedImage).toHaveAttribute(
        "src",
        new RegExp(`/api/chat/file/${fileId}`)
      );
      await expect(aiMessage).toContainText(IMAGE_GEN_AI_MESSAGE);

      await chat.screenshotContainer("chat-llm-generated-image");
    });
  });

  test.describe("Code Preview Modal", () => {
    test("clicking expand on uploaded code file opens preview modal", async ({
      page,
    }) => {
      await chat.goto();
      await mockChatEndpoint(page, buildMockStream(SHORT_AI_RESPONSE));

      // Serve our controlled Python source for any chat file fetch so the
      // modal renders deterministically regardless of the backend-assigned
      // storage file_id.
      await page.route("**/api/chat/file/**", async (route) => {
        await route.fulfill({
          status: 200,
          contentType: "text/x-python",
          body: PYTHON_CODE,
        });
      });

      const fileName = "greet.py";
      await uploadFilesToChat(page, [
        {
          name: fileName,
          mimeType: "text/x-python",
          buffer: Buffer.from(PYTHON_CODE, "utf-8"),
        },
      ]);

      await sendMessage(page, "Review this script");

      const userMessage = page.locator("#onyx-human-message").first();
      const fileDisplay = userMessage.locator("#onyx-file");
      await expect(fileDisplay).toBeVisible();

      const expandButton = fileDisplay.locator(
        'button[aria-label="Expand document"]'
      );
      await expect(expandButton).toBeVisible();
      await expandButton.click();

      const modal = page.getByRole("dialog");
      await expect(modal).toBeVisible({ timeout: 5000 });
      await expect(modal.getByText(fileName)).toBeVisible();
      await expect(
        modal
          .locator("div")
          .filter({ hasText: /python/i })
          .first()
      ).toBeVisible();
      await expect(modal.getByText("greet", { exact: true })).toBeVisible();
      await expect(modal.locator("a[download]")).toBeVisible();

      await expectElementScreenshot(modal, {
        name: "chat-code-preview-modal",
      });
    });
  });
});
