/**
 * Page Object Model for the connector setup page
 * (`/admin/connectors/<source>`).
 *
 * The page renders every connector's configuration form through the shared
 * `RenderField`/`TextFormField` machinery, so text fields are addressable by
 * their config `name` (exposed as `data-testid`) and select fields by the
 * `InputSingleSelect` whose input carries that name as its id.
 */

import { expect, type Locator, type Page } from "@playwright/test";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";
import {
  mockPassingConnectorChecks,
  runConnectorChecks,
  startChecksButton,
} from "@tests/e2e/utils/connectorChecks";

export class ConnectorSetupPage {
  readonly page: Page;
  readonly source: string;
  readonly pageTitle: Locator;
  readonly connectorNameInput: Locator;
  readonly createConnectorButton: Locator;
  /** The "Document Access" picker: everyone, specific groups, or auto sync. */
  readonly accessTypeSelect: Locator;
  /** The group picker that follows a "Specific Groups" pick. */
  readonly groupAccessPrompt: Locator;
  /** Starts the connector checks, which the configuration waits for. */
  readonly startChecksButton: Locator;

  constructor(page: Page, source: string) {
    this.page = page;
    this.source = source;
    this.pageTitle = page.locator('[aria-label="admin-page-title"]');
    // Its own test id: a credential form on the same page has a name field too.
    this.connectorNameInput = page.getByTestId("connector-name");
    this.createConnectorButton = page.getByRole("button", {
      name: "Create Connector",
      exact: true,
    });
    this.accessTypeSelect = page.getByRole("combobox", {
      name: "Document Access",
    });
    this.groupAccessPrompt = page.getByPlaceholder(
      "Add groups to restrict access to this connector"
    );
    this.startChecksButton = startChecksButton(page);
  }

  /** Make the connector checks pass without calling the source. */
  async mockChecks(): Promise<void> {
    await mockPassingConnectorChecks(this.page);
  }

  /** Run the connector checks and wait for the configuration to unlock. */
  async runChecks(): Promise<void> {
    await runConnectorChecks(this.page);
  }

  /** A single-line text field from the connector config, by its config name. */
  textField(fieldName: string): Locator {
    return this.page.getByTestId(fieldName);
  }

  /** A select field's combobox from the connector config, by its config name. */
  selectField(fieldName: string): Locator {
    return this.page.locator(`#${fieldName}`);
  }

  /** Open a select field and pick the option with this title. */
  async pickOption(fieldName: string, title: string): Promise<void> {
    await this.pick(this.selectField(fieldName), title);
  }

  /** Open the access type picker and pick an option by its title. */
  async pickAccessType(
    title: "Everyone in Your Organization" | "Specific Groups"
  ): Promise<void> {
    await this.pick(this.accessTypeSelect, title);
  }

  private async pick(select: Locator, title: string): Promise<void> {
    await select.click();
    // An option's accessible name is its title followed by its description.
    const startsWithTitle = new RegExp(
      `^${title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`
    );
    await this.page.getByRole("option", { name: startsWithTitle }).click();
  }

  /** The card for a saved account in the credential section, by its name. */
  credentialRow(credentialName: string): Locator {
    return this.page
      .getByTestId("authentication-account")
      .filter({ hasText: credentialName });
  }

  /** Pick a saved account in the credential section by its name. */
  async selectCredential(credentialName: string) {
    await this.credentialRow(credentialName)
      .getByRole("button", { name: "Use Account" })
      .click();
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
