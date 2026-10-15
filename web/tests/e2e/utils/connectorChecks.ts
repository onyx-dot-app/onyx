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
export const MOCK_DRAFT_CREDENTIAL_ID = 999_999;

/**
 * The required check: it validates the credential, so it gates the rest of the
 * form as well as Create.
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
    findings: [],
  };
}

/** A check that is not required: failed, it never blocks the form or Create. */
function commentsCheck(state: DraftCheckState["state"]): DraftCheckState {
  return {
    ...signInCheck(state),
    check_id: "comments",
    display_name: "Page comments are readable",
    required: false,
    validates_binding: false,
    message: state === "failed" ? "The account cannot read comments." : "",
  };
}

export interface MockConnectorChecksOptions {
  /** The plan also lists a non-required check, which every run fails. */
  failedOptionalCheck?: boolean;
}

/**
 * Answers the draft check endpoints: the plan lists one required check that
 * validates the credential, and every run passes it (`failedOptionalCheck` adds a
 * non-required one that fails). The real checks need a credential the source accepts.
 */
export async function mockPassingConnectorChecks(
  page: Page,
  { failedOptionalCheck = false }: MockConnectorChecksOptions = {}
): Promise<void> {
  const checksFor = (
    required: DraftCheckState["state"],
    optional: DraftCheckState["state"]
  ): DraftCheckState[] =>
    failedOptionalCheck
      ? [signInCheck(required), commentsCheck(optional)]
      : [signInCheck(required)];
  await page.route("**/api/manage/admin/connector-checks/plan", (route) => {
    const request: DraftCheckPlanRequest = route.request().postDataJSON();
    const plan: DraftCheckPlan = {
      source: request.source,
      access_type: request.access_type,
      form_errors: {},
      unknown_fields: [],
      checks: checksFor("pending", "pending"),
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
        checks: checksFor("passed", "failed"),
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
