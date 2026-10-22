/**
 * Page Object Model for the connector setup page
 * (`/admin/connectors/<source>`).
 *
 * The page renders every connector's configuration form through the shared
 * `RenderField`/`TextFormField` machinery, so text fields are addressable by
 * their config `name` (exposed as `data-testid`) and select fields by the
 * `InputSingleSelect` whose input carries that name as its id.
 */

import {
  expect,
  type Locator,
  type Page,
  type Request,
} from "@playwright/test";
import { CHECKS_CARD_ID } from "@/lib/connectors/checks/constants";
import { expectScreenshot } from "@tests/e2e/utils/visualRegression";
import {
  type MockConnectorChecksOptions,
  mockPassingConnectorChecks,
  runConnectorChecks,
  startChecksButton,
} from "@tests/e2e/utils/connectorChecks";

const CREATE_URL = "**/api/manage/admin/connector-with-credential";

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
  /** The results card of the connector checks. */
  readonly checksCard: Locator;
  /** The advisory Create opens when a non-required check failed. */
  readonly failedChecksAdvisory: Locator;
  readonly viewFailedChecksButton: Locator;
  readonly createAnywayButton: Locator;

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
    this.checksCard = page.getByTestId(CHECKS_CARD_ID);
    this.failedChecksAdvisory = page.getByRole("dialog", {
      name: "Some content won't be indexed.",
    });
    this.viewFailedChecksButton = this.failedChecksAdvisory.getByRole(
      "button",
      { name: "View Failed Checks" }
    );
    this.createAnywayButton = this.failedChecksAdvisory.getByRole("button", {
      name: "Create Connector Anyway",
    });
  }

  /** Mock the connector checks without calling the source. Options add a failed non-required check. */
  async mockChecks(options?: MockConnectorChecksOptions): Promise<void> {
    await mockPassingConnectorChecks(this.page, options);
  }

  /** Run the connector checks and wait for the configuration to unlock. */
  async runChecks(): Promise<void> {
    await runConnectorChecks(this.page);
  }

  /** Answer Create's request with a 500, so no connector is made. */
  async failCreateRequests(): Promise<void> {
    await this.page.route(CREATE_URL, (route) =>
      route.fulfill({ status: 500, json: { detail: "e2e" } })
    );
  }

  /** Resolves with the next create request. */
  waitForCreateRequest(): Promise<Request> {
    return this.page.waitForRequest(CREATE_URL);
  }

  /** A check's row in the checks card, by its display name. */
  checkRow(displayName: string): Locator {
    return this.checksCard.getByText(displayName);
  }

  /** Fold the checks card down to its summary line. */
  async foldChecksCard(): Promise<void> {
    await this.checksCard.getByRole("button", { name: "Fold" }).click();
  }

  /** Scroll the page to its end, away from the checks card. */
  async scrollToEnd(): Promise<void> {
    await this.page
      .locator("#page-wrapper-scroll-container")
      .evaluate((el) => el.scrollTo(0, el.scrollHeight));
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

  /**
   * The card for a saved account in the credential section, by its id. The
   * card is titled by its creator, so its name may not show.
   */
  credentialRow(credentialId: number): Locator {
    return this.page.getByTestId(`authentication-account-${credentialId}`);
  }

  /** Pick a saved account in the credential section by its id. */
  async selectCredential(credentialId: number) {
    await this.credentialRow(credentialId)
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
