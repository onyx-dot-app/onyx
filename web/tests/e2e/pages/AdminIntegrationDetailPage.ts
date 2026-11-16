import { type Locator, type Page, expect } from "@playwright/test";

export type PolicyLabel = "Allow" | "Ask" | "Blocked";
export type IntegrationTab = "Overview" | "Configuration" | "Actions";

/** One integration at /admin/integrations/[id]: Overview, Configuration and
 * Actions. */
export class AdminIntegrationDetailPage {
  readonly page: Page;
  readonly saveActionsButton: Locator;
  readonly refreshActionsButton: Locator;

  constructor(page: Page) {
    this.page = page;
    this.saveActionsButton = page.getByRole("button", {
      name: "Save",
      exact: true,
    });
    this.refreshActionsButton = page.getByRole("button", {
      name: "Refresh",
      exact: true,
    });
  }

  async goto(id: number, tab?: IntegrationTab): Promise<void> {
    const query = tab && tab !== "Overview" ? `?tab=${tab.toLowerCase()}` : "";
    await this.page.goto(`/admin/integrations/${id}${query}`);
  }

  async expectLoaded(name: string): Promise<void> {
    await expect(
      this.page.getByLabel("admin-page-title").getByText(name, { exact: true })
    ).toBeVisible();
  }

  async openTab(tab: IntegrationTab): Promise<void> {
    await this.page.getByRole("tab", { name: tab, exact: true }).click();
    await expect(
      this.page.getByRole("tab", { name: tab, exact: true })
    ).toHaveAttribute("aria-selected", "true");
  }

  policyButton(action: string, policy: PolicyLabel): Locator {
    return this.page
      .getByRole("group", { name: action, exact: true })
      .getByRole("button", { name: policy, exact: true });
  }

  async setActionPolicy(action: string, policy: PolicyLabel): Promise<void> {
    await this.policyButton(action, policy).click();
    await expect(this.policyButton(action, policy)).toHaveAttribute(
      "aria-pressed",
      "true"
    );
  }

  async setDefaultPolicy(policy: PolicyLabel): Promise<void> {
    await this.setActionPolicy("Default for New Actions", policy);
  }

  async saveActions(): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/actions$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.saveActionsButton.click();
    expect((await response).ok()).toBeTruthy();
    await expect(this.saveActionsButton).toBeDisabled();
  }

  async refreshActions(): Promise<void> {
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/actions\/refresh$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "POST"
    );
    await this.refreshActionsButton.click();
    expect((await response).ok()).toBeTruthy();
  }

  /** Fills the credential fields of the organization connection by label and
   * connects. */
  async connectOrganization(fields: Record<string, string>): Promise<void> {
    await this.openTab("Configuration");
    for (const [label, value] of Object.entries(fields))
      await this.page.getByLabel(label, { exact: true }).fill(value);
    const response = this.page.waitForResponse(
      (candidate) =>
        /\/api\/admin\/integrations\/\d+\/organization-connection$/.test(
          new URL(candidate.url()).pathname
        ) && candidate.request().method() === "PUT"
    );
    await this.page
      .getByRole("button", { name: "Connect", exact: true })
      .click();
    expect((await response).ok()).toBeTruthy();
    await expect(
      this.page.getByText("Connected", { exact: true })
    ).toBeVisible();
  }

  async expectSetByAdmin(action: string): Promise<void> {
    await expect(
      this.page
        .getByRole("group", { name: action, exact: true })
        .locator("xpath=../..")
        .getByText("Set by admin", { exact: true })
    ).toBeVisible();
  }
}
