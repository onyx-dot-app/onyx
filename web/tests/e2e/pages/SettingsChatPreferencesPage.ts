/**
 * Page Object Model for the Chat Preferences settings tab
 * (/app/settings/chat-preferences).
 *
 * Covers the Send Behavior While Working select, the Collapse Large Pastes
 * switch, and holding or failing their saves.
 */

import { expect, type Locator, type Page } from "@playwright/test";

type SendBehavior = "After the current step" | "Interrupt current work";

const isSendBehaviorSave = (url: URL) =>
  url.pathname.endsWith("/api/interrupt-on-send");
const isCollapseLargePastesSave = (url: URL) =>
  url.pathname.endsWith("/api/paste-as-tile");

/** A save that reached the server and whose response the browser waits for. */
export interface HeldSave {
  /** Resolves once the server has the change. */
  forwarded: Promise<void>;
  /** Sends the server's response to the browser. */
  release: () => void;
  /** Resolves once the browser has the response. */
  delivered: Promise<void>;
}

export class SettingsChatPreferencesPage {
  readonly sendBehavior: Locator;
  readonly collapseLargePastesSwitch: Locator;

  constructor(readonly page: Page) {
    this.sendBehavior = page.getByRole("combobox", {
      name: "Send Behavior While Working",
    });
    this.collapseLargePastesSwitch = page
      .locator("label")
      .filter({ hasText: "Collapse Large Pastes" })
      .getByRole("switch");
  }

  async goto(): Promise<void> {
    await this.page.goto("/app/settings/chat-preferences");
    await expect(this.sendBehavior).toBeVisible();
  }

  async chooseSendBehavior(behavior: SendBehavior): Promise<void> {
    await this.sendBehavior.click();
    await this.page
      .getByRole("option", { name: behavior, exact: true })
      .click();
  }

  async setSendBehavior(behavior: SendBehavior): Promise<void> {
    const saved = this.page.waitForResponse((response) =>
      response.url().includes("/interrupt-on-send?")
    );
    await this.chooseSendBehavior(behavior);
    expect((await saved).ok()).toBe(true);
    await expect(this.sendBehavior).toHaveValue(behavior);
  }

  async toggleCollapseLargePastes(): Promise<void> {
    await this.collapseLargePastesSwitch.click();
  }

  async expectCollapseLargePastes(enabled: boolean): Promise<void> {
    await expect(this.collapseLargePastesSwitch).toHaveAttribute(
      "aria-checked",
      String(enabled)
    );
  }

  /** Lets the next Collapse Large Pastes save reach the server, then holds its response. */
  async holdNextCollapseLargePastesSave(): Promise<HeldSave> {
    let release: () => void = () => undefined;
    const released = new Promise<void>((resolve) => {
      release = resolve;
    });
    let markForwarded: () => void = () => undefined;
    const forwarded = new Promise<void>((resolve) => {
      markForwarded = resolve;
    });
    let markDelivered: () => void = () => undefined;
    const delivered = new Promise<void>((resolve) => {
      markDelivered = resolve;
    });
    await this.page.route(
      isCollapseLargePastesSave,
      async (route) => {
        const response = await route.fetch();
        markForwarded();
        await released;
        await route.fulfill({ response });
        markDelivered();
      },
      { times: 1 }
    );
    return { forwarded, release, delivered };
  }

  /** Makes the next Send Behavior save fail without reaching the server. */
  async failNextSendBehaviorSave(): Promise<void> {
    await this.page.route(
      isSendBehaviorSave,
      (route) => route.fulfill({ status: 500 }),
      { times: 1 }
    );
  }
}
