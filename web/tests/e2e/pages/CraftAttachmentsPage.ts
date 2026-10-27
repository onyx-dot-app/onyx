import { expect, type Page } from "@playwright/test";

export class CraftAttachmentsPage {
  constructor(private readonly page: Page) {}

  async goto(sessionId: string) {
    await this.page.goto(`/craft/v1?sessionId=${sessionId}`);
    const intro = this.page.getByRole("dialog", { name: "Meet Craft" });
    const input = this.page.locator('[aria-label="Message input"]');
    await expect(intro.or(input).first()).toBeVisible();
    if (await intro.isVisible()) {
      await intro.getByRole("button", { name: "Close", exact: true }).click();
    }
    await expect(input).toHaveAttribute("aria-disabled", "false");
  }

  async attach(name: string, content: string): Promise<string> {
    const response = this.page.waitForResponse(
      (res) =>
        res.url().endsWith("/upload") && res.request().method() === "POST"
    );
    await this.page.locator('input[type="file"]').setInputFiles({
      name,
      mimeType: "text/plain",
      buffer: Buffer.from(content),
    });
    const uploaded = await response;
    expect(uploaded.ok()).toBe(true);
    const body: { path: string } = await uploaded.json();
    await expect(this.removeButton(name)).toBeVisible();
    return body.path;
  }

  private removeButton(name: string) {
    return this.page.getByRole("button", {
      name: `Remove ${name}`,
      exact: true,
    });
  }

  async remove(name: string) {
    await this.removeButton(name).click();
    await this.expectNotAttached(name);
  }

  async expectNotAttached(name: string) {
    await expect(this.removeButton(name)).toHaveCount(0);
  }

  async expectStored(sessionId: string, path: string, content: string) {
    const encoded = path.split("/").map(encodeURIComponent).join("/");
    const response = await this.page.request.get(
      `/api/build/sessions/${sessionId}/artifacts/${encoded}`
    );
    expect(response.ok()).toBe(true);
    expect(await response.text()).toBe(content);
  }

  async reload() {
    await this.page.reload();
    await this.page.waitForLoadState("networkidle");
    await expect(
      this.page.locator('[aria-label="Message input"]')
    ).toBeVisible();
  }
}
