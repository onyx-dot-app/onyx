/**
 * Page Object Model for the Language Models admin page
 * (/admin/language-models): provider cards and the Cost Overrides panel.
 *
 * Provider and override cards are labelled with their bare names (a
 * provider's name, an override's model display name). An override card's
 * description also shows its provider's name, so text locators would match
 * both cards; these locate by exact label instead.
 */

import type { Locator, Page } from "@playwright/test";

export class AdminLanguageModelsPage {
  readonly page: Page;
  readonly costOverridesLoadError: Locator;

  constructor(page: Page) {
    this.page = page;
    this.costOverridesLoadError = page.getByText(
      "Failed to load cost overrides."
    );
  }

  /** The configured provider's card. */
  providerCard(providerName: string): Locator {
    return this.page.getByLabel(providerName, { exact: true });
  }

  /** A cost override's card, by its model display name. */
  costOverrideCard(modelDisplayName: string): Locator {
    return this.page.getByLabel(modelDisplayName, { exact: true });
  }
}
