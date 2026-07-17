/**
 * Page Object Model for the add-connector wizard
 * (`/admin/connectors/<source>?step=1`).
 *
 * The wizard renders every connector's configuration form through the shared
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
      name: "Create Connector",
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

  /**
   * Navigate straight to the configuration step of the wizard. Connectors
   * without a credential step (e.g. web) render their form here.
   */
  async goto() {
    await this.page.goto(`/admin/connectors/${this.source}?step=1`);
    await expect(this.pageTitle).toBeVisible({ timeout: 10_000 });
  }

  /**
   * Submit the form and wait for the post-creation redirect to the connector
   * status page. Creation validates the config server-side (up to ~10s in the
   * UI), so allow a generous timeout.
   */
  async submitAndWaitForCreation() {
    await this.createConnectorButton.click();
    await this.page.waitForURL("**/admin/indexing/status**", {
      timeout: 30_000,
    });
  }

  /** Capture a full-page visual snapshot of the wizard. */
  async expectScreenshot(name: string) {
    await expectScreenshot(this.page, { name });
  }
}
