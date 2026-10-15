import {
  expect,
  type Download,
  type Page,
  type Response,
} from "@playwright/test";
import { boolean, mixed, object, string, type ObjectSchema } from "yup";
import type {
  ApiDetailedSessionResponse,
  ApiInteractiveTurnResponse,
  ApiSandboxResponse,
} from "@/app/craft/types/streamingTypes";
import { CraftAttachmentsPage } from "@tests/e2e/pages/CraftAttachmentsPage";
import {
  MOCK_LLM_DEFAULT_MODEL,
  MOCK_LLM_PROVIDER_NAME,
} from "@tests/e2e/utils/mockLlm";

const sessionIdentitySchema: ObjectSchema<
  Pick<ApiDetailedSessionResponse, "id">
> = object({ id: string().uuid().required() }).required();

const sessionReadinessSchema: ObjectSchema<
  Pick<ApiDetailedSessionResponse, "session_loaded_in_sandbox"> & {
    sandbox: Pick<ApiSandboxResponse, "id" | "status">;
  }
> = object({
  session_loaded_in_sandbox: boolean().required(),
  sandbox: object({
    id: string().uuid().required(),
    status: mixed<ApiSandboxResponse["status"]>()
      .oneOf(["provisioning", "running", "sleeping", "terminated", "failed"])
      .required(),
  }).required(),
}).required();

const turnIdentitySchema: ObjectSchema<
  Pick<ApiInteractiveTurnResponse, "turn_id" | "session_id">
> = object({
  turn_id: string().uuid().required(),
  session_id: string().uuid().required(),
}).required();

export class CraftSessionPage {
  private readonly navigation: CraftAttachmentsPage;

  constructor(private readonly page: Page) {
    this.navigation = new CraftAttachmentsPage(page);
  }

  async goto(sessionId: string): Promise<void> {
    await this.navigation.goto(sessionId);
  }

  observeSessionCreation(): Promise<Response> {
    return this.page.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/build/sessions" &&
        response.request().method() === "POST",
      { timeout: 240_000 }
    );
  }

  async createdSessionId(response: Response): Promise<string> {
    const body: unknown = await response.json();
    const session = await sessionIdentitySchema.validate(body, {
      strict: true,
    });
    return session.id;
  }

  async expectCreatedSessionReady(response: Response): Promise<string> {
    expect(response.status()).toBe(200);
    const body: unknown = await response.json();
    const session = await sessionReadinessSchema.validate(body, {
      strict: true,
    });
    expect(session.session_loaded_in_sandbox).toBe(true);
    expect(session.sandbox.status).toBe("running");
    return session.sandbox.id;
  }

  async selectMockModel(): Promise<void> {
    const trigger = this.page.locator('[aria-haspopup="dialog"][aria-busy]');
    await expect(trigger).toHaveAttribute("aria-busy", "false");
    await trigger.click();
    const picker = this.page.getByRole("dialog").filter({
      hasText: "Recommended Models Only",
    });
    const recommendedOnly = picker.getByRole("switch");
    if ((await recommendedOnly.getAttribute("aria-checked")) === "true") {
      await recommendedOnly.click();
    }
    const provider = picker.getByRole("button", {
      name: MOCK_LLM_PROVIDER_NAME,
      exact: true,
    });
    if ((await provider.getAttribute("aria-expanded")) !== "true") {
      await provider.click();
    }
    await picker
      .getByText(MOCK_LLM_DEFAULT_MODEL.displayName, { exact: true })
      .click();
    await expect(trigger).toHaveText(MOCK_LLM_DEFAULT_MODEL.displayName);
  }

  async send(
    message: string,
    options?: { sessionId: ApiDetailedSessionResponse["id"] }
  ): Promise<string> {
    await this.page
      .getByRole("textbox", { name: "Message input" })
      .fill(message);
    const sent = this.page.waitForResponse(
      (response) =>
        (options
          ? new URL(response.url()).pathname ===
            `/api/build/sessions/${options.sessionId}/send-message`
          : response.url().endsWith("/send-message")) &&
        response.request().method() === "POST"
    );
    await this.page.getByRole("button", { name: "Send", exact: true }).click();
    const response = await sent;
    expect(response.ok()).toBe(true);
    const body: unknown = await response.json();
    const turn = await turnIdentitySchema.validate(body, { strict: true });
    if (options) {
      expect(turn.session_id).toBe(options.sessionId);
      await expect(this.page).toHaveURL(
        (url) =>
          url.pathname === "/craft/v1" &&
          url.searchParams.get("sessionId") === options.sessionId
      );
    }
    return turn.turn_id;
  }

  async expectPartialReply(text: string): Promise<void> {
    await expect(this.page.getByText(text, { exact: true })).toBeVisible();
    await expect(
      this.page.getByRole("button", { name: "Stop generating", exact: true })
    ).toBeEnabled();
  }

  async expectCompletedReply(text: string, timeout?: number): Promise<void> {
    await expect(this.page.getByText(text, { exact: false })).toBeVisible({
      timeout,
    });
    await expect(
      this.page.getByRole("button", { name: "Send", exact: true })
    ).toBeVisible();
  }

  async stop(): Promise<void> {
    const interrupted = this.page.waitForResponse(
      (response) =>
        response.url().includes("/interrupt") &&
        response.request().method() === "POST"
    );
    await this.page
      .getByRole("button", { name: "Stop generating", exact: true })
      .click();
    const response = await interrupted;
    expect(response.ok()).toBe(true);
    expect(await response.json()).toMatchObject({ interrupted: true });
    await expect(
      this.page.getByRole("button", { name: "Stop generating", exact: true })
    ).toBeDisabled();
    await expect(
      this.page.getByRole("button", { name: "Send", exact: true })
    ).toBeVisible();
  }

  async openOutput(name: string, content: string): Promise<void> {
    await this.page.getByRole("link", { name, exact: true }).click();
    await expect(this.page.getByTestId("url-bar-pill")).toContainText(name);
    await expect(
      this.page.getByText(content.trim(), { exact: true })
    ).toBeVisible();
  }

  async downloadOutput(name: string): Promise<Download> {
    await this.page
      .getByRole("button", { name: "Artifacts", exact: true })
      .click();
    const output = this.page.getByRole("button", {
      name: `Open ${name}`,
      exact: true,
    });
    await expect(output).toBeVisible();
    const downloaded = this.page.waitForEvent("download");
    await output.getByRole("button", { name: "Download", exact: true }).click();
    return downloaded;
  }

  async expectGeneratedPreview({
    sessionId,
    heading,
  }: {
    sessionId: ApiDetailedSessionResponse["id"];
    heading: string;
  }): Promise<void> {
    await this.page
      .getByRole("button", { name: "Preview", exact: true })
      .click();
    const preview = this.page.getByTitle("Web App Preview", { exact: true });
    await expect(preview).toHaveAttribute(
      "src",
      `${new URL(this.page.url()).origin}/api/build/sessions/${sessionId}/webapp`
    );
    const app = preview.contentFrame();
    await expect(
      app.getByRole("heading", { name: heading, exact: true })
    ).toBeVisible();
    await app.getByRole("button", { name: "Count 0", exact: true }).click();
    await expect(
      app.getByRole("button", { name: "Count 1", exact: true })
    ).toBeVisible();
  }

  async reload(): Promise<void> {
    await this.navigation.reload();
  }
}
