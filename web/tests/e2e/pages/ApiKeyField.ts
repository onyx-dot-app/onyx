import type { Locator } from "@playwright/test";

/** The shared API key field (`ApiTokenField`) inside a form or modal. */
export class ApiKeyField {
  readonly input: Locator;

  constructor(scope: Locator) {
    this.input = scope.getByLabel(/api key/i);
  }

  /** Types a new key, replacing a saved key or earlier text. */
  async fill(value: string): Promise<void> {
    await this.input.waitFor({ state: "visible", timeout: 5000 });
    await this.input.clear();
    await this.input.fill(value);
  }
}
