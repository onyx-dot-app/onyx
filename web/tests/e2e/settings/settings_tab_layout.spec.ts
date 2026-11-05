import { expect, test } from "@playwright/test";

// Headless Chromium hides scrollbars by default. Show them, so a scrollbar
// that appears or goes away changes the layout as it does for real users.
test.use({
  storageState: "admin_auth.json",
  launchOptions: { ignoreDefaultArgs: ["--hide-scrollbars"] },
});

interface SettingsLayoutBox {
  navX: number;
  navWidth: number;
  scrollContainerClientWidth: number;
}

test.describe("Settings tab layout", () => {
  // Every tab must keep the same frame, whether its content scrolls or not.
  // The test discovers the tabs from the navigation, so new tabs are covered.
  test("should not shift the layout when switching tabs", async ({ page }) => {
    await page.goto("/app/settings/general");
    const nav = page.getByTestId("settings-left-tab-navigation");
    const tabs = nav.locator("a");
    await expect(tabs.first()).toBeVisible({ timeout: 10_000 });

    const hrefs = await tabs.evaluateAll((links) =>
      links.map((link) => link.getAttribute("href") ?? "")
    );
    expect(hrefs.length).toBeGreaterThan(1);

    const measureLayout = (): Promise<SettingsLayoutBox> =>
      page.evaluate(() => {
        const navBox = document
          .querySelector('[data-testid="settings-left-tab-navigation"]')!
          .getBoundingClientRect();
        const scrollContainer = document.getElementById(
          "page-wrapper-scroll-container"
        )!;
        return {
          navX: navBox.x,
          navWidth: navBox.width,
          scrollContainerClientWidth: scrollContainer.clientWidth,
        };
      });

    // Makes the page taller than the viewport, so the test does not depend
    // on how much content each tab has in the test data.
    const setForcedOverflow = (enabled: boolean) =>
      page.evaluate((enabled) => {
        const id = "settings-layout-test-spacer";
        document.getElementById(id)?.remove();
        if (!enabled) return;
        const spacer = document.createElement("div");
        spacer.id = id;
        spacer.style.height = "200vh";
        spacer.style.flexShrink = "0";
        document
          .getElementById("page-wrapper-scroll-container")!
          .appendChild(spacer);
      }, enabled);

    let baseline: SettingsLayoutBox | undefined;
    for (const href of hrefs) {
      await nav.locator(`a[href="${href}"]`).click();
      await expect(page).toHaveURL(href);
      await page.waitForLoadState("networkidle");

      const layout = await measureLayout();
      baseline ??= layout;
      expect(layout, `layout shifted on ${href}`).toEqual(baseline);

      await setForcedOverflow(true);
      expect(
        await measureLayout(),
        `layout shifted on ${href} when its content scrolls`
      ).toEqual(baseline);
      await setForcedOverflow(false);
    }
  });
});
