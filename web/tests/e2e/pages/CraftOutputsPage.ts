import { expect, type Locator, type Page } from "@playwright/test";

export class CraftOutputsPage {
  readonly page: Page;
  readonly toggle: Locator;
  readonly expand: Locator;
  readonly restore: Locator;
  readonly panel: Locator;
  readonly divider: Locator;
  readonly workspace: Locator;
  readonly plus: Locator;
  readonly sandboxStatus: Locator;
  constructor(page: Page) {
    this.page = page;
    this.toggle = page.getByRole("button", { name: /^(Open|Close) outputs$/ });
    this.expand = page.getByRole("button", {
      name: "Expand outputs",
      exact: true,
    });
    this.restore = page.getByRole("button", {
      name: "Restore outputs",
      exact: true,
    });
    this.panel = page.getByTestId("output-panel");
    this.sandboxStatus = page.getByTestId("sandbox-status");
    this.divider = page.getByRole("separator", { name: "Resize outputs" });
    this.workspace = page.locator("[data-output-mode]");
    this.plus = page.getByRole("button", { name: "Open a tab", exact: true });
  }
  async goto(sessionId?: string) {
    await this.page.goto(
      sessionId ? `/craft/v1?sessionId=${sessionId}` : "/craft/v1"
    );
    const intro = this.page.getByRole("dialog", { name: "Meet Craft" });
    await expect(intro.or(this.toggle).first()).toBeVisible();
    if (await intro.isVisible())
      await intro.getByRole("button", { name: "Close", exact: true }).click();
    await expect(this.toggle).toBeVisible();
  }
  async exitFullMode() {
    await this.page.keyboard.press("Escape");
    await this.expectMode("medium");
  }
  async expectMode(mode: "closed" | "medium" | "full") {
    await expect(this.workspace).toHaveAttribute("data-output-mode", mode);
    if (mode === "full") {
      await expect(this.sandboxStatus).toBeHidden();
      await expect
        .poll(async () => {
          const panel = await this.panel.boundingBox();
          const workspace = await this.workspace.boundingBox();
          return panel && workspace
            ? Math.abs(panel.width - workspace.width)
            : Infinity;
        })
        .toBeLessThan(1);
    }
  }
  async expectSandboxStatusVisible() {
    await expect(this.sandboxStatus).toBeVisible();
    await expect
      .poll(() =>
        this.sandboxStatus.evaluate(
          (element) => element.scrollWidth - element.clientWidth
        )
      )
      .toBeLessThanOrEqual(1);
  }
  async open() {
    await this.toggle.click();
    await this.expectMode("medium");
  }
  async close() {
    await this.toggle.click();
    await this.expectMode("closed");
  }
  async openTab(name: "Outputs" | "All Files" | "Apps") {
    await this.plus.click();
    await this.page.getByRole("menuitem", { name, exact: true }).click();
  }
  async expectTabs(names: string[]) {
    await expect(this.page.getByRole("tab")).toHaveText(names);
  }
  async closeTab(name: string) {
    await this.page.getByRole("tab", { name, exact: true }).hover();
    await this.page
      .getByRole("button", { name: `Close ${name}`, exact: true })
      .click();
  }
  async expectEmpty() {
    await expect(
      this.panel.getByText("Choose a workspace view", { exact: true })
    ).toBeVisible();
  }
  async expectSearch(query: string) {
    await expect(
      this.page.getByRole("textbox", { name: "Search files", exact: true })
    ).toHaveValue(query);
  }
  async search(query: string) {
    await this.page
      .getByRole("textbox", { name: "Search files", exact: true })
      .fill(query);
  }
  async expectHeaderStable(action: () => Promise<void>) {
    const frames = this.toggle.evaluate(async (element) => {
      const positions: number[][] = [];
      for (let frame = 0; frame < 36; frame++) {
        await new Promise<void>((resolve) =>
          requestAnimationFrame(() => resolve())
        );
        const bounds = element.getBoundingClientRect();
        positions.push([bounds.x, bounds.y, bounds.width, bounds.height]);
      }
      return positions;
    });
    const initial = await this.toggle.boundingBox();
    if (!initial) throw new Error("Outputs control has no bounds");
    await action();
    const samples = await frames;
    const maximumShift = Math.max(
      ...samples.map((bounds) =>
        Math.max(
          Math.abs((bounds[0] ?? 0) - initial.x),
          Math.abs((bounds[1] ?? 0) - initial.y),
          Math.abs((bounds[2] ?? 0) - initial.width),
          Math.abs((bounds[3] ?? 0) - initial.height)
        )
      )
    );
    expect(maximumShift).toBeLessThan(1);
    await expect
      .poll(async () => {
        const bounds = await this.toggle.boundingBox();
        return bounds
          ? Math.max(
              Math.abs(bounds.x - initial.x),
              Math.abs(bounds.y - initial.y),
              Math.abs(bounds.width - initial.width),
              Math.abs(bounds.height - initial.height)
            )
          : Infinity;
      })
      .toBeLessThan(1);
  }
  async reload() {
    await this.page.reload({ waitUntil: "domcontentloaded" });
    await expect(this.toggle).toBeVisible();
  }
  async expectOutputPreview(path: string) {
    const tile = this.panel.getByRole("button", { name: path, exact: true });
    await expect(tile).toBeVisible();
    const image = tile.locator("img");
    await expect(image).toHaveAttribute("src", /^data:image\/svg\+xml;base64,/);
    await expect(image).toHaveJSProperty("complete", true);
    await expect(image).not.toHaveJSProperty("naturalWidth", 0);
  }
  async expectOutputAbsent(path: string) {
    await expect(
      this.panel.getByRole("button", { name: path, exact: true })
    ).toHaveCount(0);
  }
  async quickResizeLeft(pixels: number): Promise<number> {
    await this.divider.hover();
    const divider = await this.divider.boundingBox();
    const workspace = await this.workspace.boundingBox();
    if (!divider || !workspace)
      throw new Error("Workspace resize bounds are missing");
    const targetX = divider.x + divider.width / 2 - pixels;
    const y = divider.y + divider.height / 2;
    const expectedWidth = Math.round(workspace.x + workspace.width - targetX);
    await this.page.mouse.move(divider.x + divider.width / 2, y);
    await this.page.mouse.down();
    await this.page.mouse.move(targetX, y, { steps: 1 });
    await this.page.mouse.up();
    await this.expectPanelWidth(expectedWidth);
    return expectedWidth;
  }
  async expectPanelWidth(width: number) {
    await expect(this.divider).toHaveAttribute("aria-valuenow", String(width));
  }
  async resizeKeyboard() {
    await this.divider.focus();
    await this.divider.press("ArrowLeft");
    await expect(this.divider).toHaveAttribute("aria-valuenow", /\d+/);
    await this.divider.press("Home");
    await expect(this.divider).toHaveAttribute("aria-valuenow", "280");
    await this.divider.press("End");
    await this.divider.dblclick();
  }
  async reorderBrowserLeft() {
    const browser = this.page.getByRole("tab", {
      name: "Apps",
      exact: true,
    });
    await browser.focus();
    await browser.press("Alt+ArrowLeft");
  }
  async screenshot(name: string) {
    await this.page.screenshot({ path: `output/playwright/${name}.png` });
  }
}
