import { expect } from "@playwright/test";
import { ChatPage } from "@tests/e2e/chat/ChatPage";
export class NativeChatPage extends ChatPage {
  async send(text: string): Promise<void> {
    await this.inputBar.fill(text);
    await this.inputBar.send();
  }
  async expectAnswer(text: string): Promise<void> {
    await expect(this.aiMessages.last()).toContainText(text);
  }
  async expectStreamingText(text: string): Promise<void> {
    await expect(
      this.page.getByText(text, { exact: false }).last()
    ).toBeVisible();
  }
  async expectCitation(): Promise<void> {
    await expect(
      this.aiMessages
        .last()
        .getByRole("button", { name: "Native evidence source", exact: true })
    ).toBeVisible();
  }
  async expectStopped(): Promise<void> {
    await expect(this.inputBar.sendButton).toBeDisabled();
    await expect(this.inputBar.textbox).toBeVisible();
  }
  async expandTimeline(): Promise<void> {
    await this.page
      .getByRole("button", { name: "Expand timeline", exact: true })
      .first()
      .click();
  }
  async stop(): Promise<void> {
    await this.inputBar.sendButton.click();
  }
}
