import { expect, type Page } from "@playwright/test";
import type {
  DraftCheckPlan,
  DraftCheckPlanRequest,
  DraftCheckRunRequest,
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";

const RUN_ID = "e2e-check-run";
// The draft a real run would save a typed account as. Nothing stores it.
const MOCK_DRAFT_CREDENTIAL_ID = 999_999;

/**
 * The one check the mock knows: required, and it validates the credential, so
 * it gates the rest of the form as well as Create.
 */
function signInCheck(state: DraftCheckState["state"]): DraftCheckState {
  return {
    check_id: "authentication",
    display_name: "Authentication",
    capability: "indexing",
    required: true,
    state,
    message: "",
    missing_fields: [],
    invalid_fields: [],
    remediation: null,
    docs_link: null,
    duration_ms: state === "passed" ? 1 : null,
    from_cache: false,
    validates_binding: true,
  };
}

/**
 * Answers the draft check endpoints: the plan lists one required check that
 * validates the credential, and every run passes it. The real checks call the
 * source with the credential, which a test credential cannot pass.
 */
export async function mockPassingConnectorChecks(page: Page): Promise<void> {
  await page.route("**/api/manage/admin/connector-checks/plan", (route) => {
    const request: DraftCheckPlanRequest = route.request().postDataJSON();
    const plan: DraftCheckPlan = {
      source: request.source,
      access_type: request.access_type,
      form_errors: {},
      unknown_fields: [],
      checks: [signInCheck("pending")],
    };
    return route.fulfill({ json: plan });
  });
  let latest: DraftCheckRunSnapshot | null = null;
  await page.route(
    "**/api/manage/admin/connector-checks/runs",
    async (route) => {
      const request: DraftCheckRunRequest = route.request().postDataJSON();
      latest = {
        run_id: RUN_ID,
        draft_key: request.draft_key,
        source: request.source,
        credential_id:
          "credential_id" in request
            ? request.credential_id
            : MOCK_DRAFT_CREDENTIAL_ID,
        access_type: request.access_type,
        status: "completed",
        form_errors: {},
        unknown_fields: [],
        checks: [signInCheck("passed")],
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
