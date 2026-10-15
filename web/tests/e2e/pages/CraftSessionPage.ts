import { expect, type Download, type Page } from "@playwright/test";
import { CraftAttachmentsPage } from "@tests/e2e/pages/CraftAttachmentsPage";
import {
  MOCK_LLM_DEFAULT_MODEL,
  MOCK_LLM_PROVIDER_NAME,
} from "@tests/e2e/utils/mockLlm";

export class CraftSessionPage {
  private readonly navigation: CraftAttachmentsPage;

  constructor(private readonly page: Page) {
    this.navigation = new CraftAttachmentsPage(page);
  }

  async goto(sessionId: string): Promise<void> {
    await this.navigation.goto(sessionId);
  }

  async selectMockModel(): Promise<void> {
    const trigger = this.page.locator('[aria-haspopup="dialog"][aria-busy]');
    await expect(trigger).toHaveAttribute("aria-busy", "false");
    await trigger.click();
    const picker = this.page.getByRole("dialog").filter({
      hasText: "Recommended Models Only",
    });
    const recommendedOnly = picker.getByRole("switch");
    if ((await recommendedOnly.getAttribute("aria-checked")) === "true") {
      await recommendedOnly.click();
    }
    const provider = picker.getByRole("button", {
      name: MOCK_LLM_PROVIDER_NAME,
      exact: true,
    });
    if ((await provider.getAttribute("aria-expanded")) !== "true") {
      await provider.click();
    }
    await picker
      .getByText(MOCK_LLM_DEFAULT_MODEL.displayName, { exact: true })
      .click();
    await expect(trigger).toHaveText(MOCK_LLM_DEFAULT_MODEL.displayName);
  }

  async send(message: string): Promise<string> {
    await this.page
      .getByRole("textbox", { name: "Message input" })
      .fill(message);
    const sent = this.page.waitForResponse(
      (response) =>
        response.url().endsWith("/send-message") &&
        response.request().method() === "POST"
    );
    await this.page.getByRole("button", { name: "Send", exact: true }).click();
    const response = await sent;
    expect(response.ok()).toBe(true);
    const turn: { turn_id: string } = await response.json();
    expect(turn.turn_id).toMatch(/^[a-f0-9-]{36}$/);
    return turn.turn_id;
  }

  async expectPartialReply(text: string): Promise<void> {
    await expect(this.page.getByText(text, { exact: true })).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "Stop generating", exact: true })
    ).toBeEnabled();
  }

  async expectCompletedReply(text: string): Promise<void> {
    await expect(this.page.getByText(text, { exact: false })).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "Send", exact: true })
    ).toBeVisible();
  }

  async stop(): Promise<void> {
    const interrupted = this.page.waitForResponse(
      (response) =>
        response.url().includes("/interrupt") &&
        response.request().method() === "POST"
    );
    await this.page
      .getByRole("button", { name: "Stop generating", exact: true })
      .click();
    const response = await interrupted;
    expect(response.ok()).toBe(true);
    expect(await response.json()).toMatchObject({ interrupted: true });
    await expect(
      this.page.getByRole("button", { name: "Stop generating", exact: true })
    ).toBeHidden();
    await expect(
      this.page.getByRole("button", { name: "Send", exact: true })
    ).toBeVisible();
  }

  async openOutput(name: string, content: string): Promise<void> {
    await this.page.getByRole("link", { name, exact: true }).click();
    await expect(this.page.getByTestId("url-bar-pill")).toContainText(name);
    await expect(
      this.page.getByText(content.trim(), { exact: true })
    ).toBeVisible();
  }

  async downloadOutput(name: string): Promise<Download> {
    await this.page
      .getByRole("button", { name: "Artifacts", exact: true })
      .click();
    const output = this.page.getByRole("button", {
      name: `Open ${name}`,
      exact: true,
    });
    await expect(output).toBeVisible();
    const downloaded = this.page.waitForEvent("download");
    await output.getByRole("button", { name: "Download", exact: true }).click();
    return downloaded;
  }

  async reload(): Promise<void> {
    await this.navigation.reload();
  }
}
