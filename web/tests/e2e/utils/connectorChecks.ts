import { expect, type Page } from "@playwright/test";
import type {
  DraftCheckRunRequest,
  DraftCheckRunSnapshot,
} from "@/lib/connectors/checks/types";

const RUN_ID = "e2e-check-run";

/**
 * Answers the draft check-run endpoints with a run whose one required check
 * passed. The real checks call the source with the credential, which a test
 * credential cannot pass.
 */
export async function mockPassingConnectorChecks(page: Page): Promise<void> {
  let latest: DraftCheckRunSnapshot | null = null;
  await page.route(
    "**/api/manage/admin/connector-checks/runs",
    async (route) => {
      const request: DraftCheckRunRequest = route.request().postDataJSON();
      latest = {
        run_id: RUN_ID,
        draft_key: request.draft_key,
        source: request.source,
        credential_id: request.credential_id,
        access_type: request.access_type,
        status: "completed",
        form_errors: {},
        unknown_fields: [],
        checks: [
          {
            check_id: "authentication",
            display_name: "Authentication",
            capability: "indexing",
            required: true,
            state: "passed",
            message: "",
            missing_fields: [],
            invalid_fields: [],
            remediation: null,
            docs_link: null,
            duration_ms: 1,
            from_cache: false,
            validates_binding: false,
          },
        ],
      };
      await route.fulfill({ json: latest });
    }
  );
  await page.route(
    `**/api/manage/admin/connector-checks/runs/${RUN_ID}`,
    (route) => route.fulfill({ json: latest })
  );
}

/** The Start Checks button of the checks prompt. */
export function startChecksButton(page: Page) {
  return page.getByRole("button", { name: "Start Checks", exact: true });
}

/**
 * Starts the connector checks and waits until they pass. Needs
 * `mockPassingConnectorChecks`.
 */
export async function runConnectorChecks(page: Page): Promise<void> {
  await expect(startChecksButton(page)).toBeEnabled({ timeout: 10_000 });
  await startChecksButton(page).click();
  await expect(page.getByTestId("connector-name")).toBeEnabled({
    timeout: 10_000,
  });
}
