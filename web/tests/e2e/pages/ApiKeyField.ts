import type { Locator } from "@playwright/test";

/** The shared API key field (`ApiTokenField`) inside a form or modal. */
export class ApiKeyField {
  readonly input: Locator;
  /** A saved key shows as a tag with its masked value, e.g. "sk-a...1111". */
  readonly savedKey: Locator;

  constructor(scope: Locator) {
    this.input = scope.getByLabel(/api key/i);
    this.savedKey = scope.getByText(/^\S{4}\.\.\.\S{4}$|^•+$/);
  }

  /** Types a new key, replacing a saved key or earlier text. */
  async fill(value: string): Promise<void> {
    await this.input.waitFor({ state: "visible", timeout: 5000 });
    await this.input.clear();
    await this.input.fill(value);
  }
}
