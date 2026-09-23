/**
 * Page Object Model for the connector setup page
 * (`/admin/connectors/<source>`).
 *
 * The page renders every connector's configuration form through the shared
 * `RenderField`/`TextFormField` machinery, so text fields are addressable by
 * their config `name` (exposed as `data-testid`) and select fields by their
 * native `<select name=...>` element.
 */

import { expect, type Locator, type Page } from "@playwright/test";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";

export class ConnectorSetupPage {
  readonly page: Page;
  readonly source: string;
  readonly pageTitle: Locator;
  readonly connectorNameInput: Locator;
  readonly createConnectorButton: Locator;

  constructor(page: Page, source: string) {
    this.page = page;
    this.source = source;
    this.pageTitle = page.locator('[aria-label="admin-page-title"]');
    this.connectorNameInput = page.getByTestId("name");
    this.createConnectorButton = page.getByRole("button", {
      name: "Connect",
      exact: true,
    });
  }

  /** A single-line text field from the connector config, by its config name. */
  textField(fieldName: string): Locator {
    return this.page.getByTestId(fieldName);
  }

  /** A select field from the connector config, by its config name. */
  selectField(fieldName: string): Locator {
    return this.page.locator(`select[name="${fieldName}"]`);
  }

  /** The row for a credential in the credential section, by its name. */
  credentialRow(credentialName: string): Locator {
    return this.page.getByRole("row", { name: credentialName });
  }

  /** Pick a credential in the credential section by its name. */
  async selectCredential(credentialName: string) {
    await this.credentialRow(credentialName).getByRole("radio").click();
  }

  /**
   * Navigate to the setup page. Every section renders on one page; connectors
   * without a credential (e.g. web) skip the credential section.
   */
  async goto() {
    await this.page.goto(`/admin/connectors/${this.source}`);
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  /**
   * Submit the form and wait for the post-creation redirect to the connector
   * status page. Creation validates the config server-side (up to ~10s in the
   * UI), so allow a generous timeout.
   */
  async submitAndWaitForCreation() {
    await this.createConnectorButton.click();
    await this.page.waitForURL("**/admin/indexing-status**", {
      timeout: 30_000,
    });
  }

  /** Capture a full-page visual snapshot of the setup page. */
  async expectScreenshot(name: string) {
    await expectScreenshot(this.page, { name });
  }
}
