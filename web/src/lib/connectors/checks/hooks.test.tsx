import type { CredentialRef } from "@/lib/credentials/types";
import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { Formik, useFormikContext } from "formik";
import type { ReactNode } from "react";
import { useConnectorChecks } from "@/lib/connectors/checks/hooks";
import {
  fetchDraftCheckPlan,
  startDraftCheckRun,
} from "@/lib/connectors/checks/svc";
import type {
  DraftCheckPlan,
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/connectors/checks/svc", () => ({
  startDraftCheckRun: jest.fn(),
  fetchDraftCheckPlan: jest.fn(),
}));
// A run fetch returns what the latest start request returned.
jest.mock("@/lib/fetcher", () => ({
  errorHandlingFetcher: jest.fn(async () => {
    const { startDraftCheckRun } = jest.requireMock(
      "@/lib/connectors/checks/svc"
    );
    return startDraftCheckRun.mock.results.at(-1)?.value;
  }),
}));
// No credential-bound fields: the credential alone binds a result. Every form
// value is part of what a run checks.
jest.mock("@/lib/connectors/connectors", () => ({
  useConnectorConfiguration: () => ({ values: [], advanced_values: [] }),
}));
jest.mock("@/lib/connectors/utils", () => ({
  splitCredentialBoundFields: () => ({ values: [], advancedValues: [] }),
}));
jest.mock("@/lib/connectors/checks/formState", () => ({
  connectorFormState: (_configuration: unknown, values: unknown) => values,
}));

const startMock = startDraftCheckRun as jest.MockedFunction<
  typeof startDraftCheckRun
>;
const planMock = fetchDraftCheckPlan as jest.MockedFunction<
  typeof fetchDraftCheckPlan
>;

function check(
  overrides: Partial<DraftCheckState> & Pick<DraftCheckState, "state">
): DraftCheckState {
  return {
    check_id: "auth",
    display_name: "Auth",
    capability: "indexing",
    required: true,
    message: "",
    missing_fields: [],
    invalid_fields: [],
    remediation: null,
    docs_link: null,
    duration_ms: null,
    from_cache: false,
    validates_binding: false,
    ...overrides,
  };
}

function run(
  checks: DraftCheckState[],
  status: DraftCheckRunSnapshot["status"] = "completed"
): DraftCheckRunSnapshot {
  return {
    run_id: "run-1",
    draft_key: "draft",
    source: ValidSources.Confluence,
    credential_id: 1,
    access_type: "public",
    status,
    form_errors: {},
    unknown_fields: [],
    checks,
  };
}

function plan(checks: DraftCheckState[]): DraftCheckPlan {
  return {
    source: ValidSources.Confluence,
    access_type: "public",
    form_errors: {},
    unknown_fields: [],
    checks,
  };
}

const BINDING = check({
  check_id: "sign_in",
  state: "pending",
  validates_binding: true,
});
const CONTENT = check({ check_id: "space", state: "waiting" });

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map() }}>
      <Formik initialValues={{}} onSubmit={() => {}}>
        {() => children}
      </Formik>
    </SWRConfig>
  );
}

function refFor(credentialId: number | null): CredentialRef | null {
  return credentialId === null ? null : { credential_id: credentialId };
}

function renderChecks(credentialId: number | null = 1) {
  return renderHook(
    (props: { credentialId: number | null }) => ({
      checks: useConnectorChecks({
        source: ValidSources.Confluence,
        credential: refFor(props.credentialId),
      }),
      form: useFormikContext<Record<string, unknown>>(),
    }),
    { initialProps: { credentialId }, wrapper }
  );
}

beforeEach(() => {
  startMock.mockReset();
  planMock.mockReset();
  planMock.mockResolvedValue(plan([BINDING, CONTENT]));
});

it("runs nothing until begin, and resets when the credential changes", async () => {
  startMock.mockResolvedValue(
    run([check({ ...BINDING, state: "passed" }), CONTENT])
  );
  const { result, rerender } = renderChecks();

  expect(result.current.checks.status).toBe("notStarted");
  act(() => result.current.checks.begin());
  await waitFor(() => expect(result.current.checks.status).toBe("passed"));

  rerender({ credentialId: 2 });
  expect(result.current.checks.status).toBe("notStarted");
  expect(result.current.checks.formUnlocked).toBe(false);
  expect(startMock).toHaveBeenCalledTimes(1);
});

it("unlocks the form once the binding checks pass, before Create can run", async () => {
  startMock.mockResolvedValue(
    run([check({ ...BINDING, state: "passed" }), CONTENT])
  );
  const { result } = renderChecks();
  await waitFor(() => expect(result.current.checks.plan).toBeDefined());
  expect(result.current.checks.formUnlocked).toBe(false);

  act(() => result.current.checks.begin());

  // The content check still waits for its field, so Create stays locked.
  await waitFor(() => expect(result.current.checks.formUnlocked).toBe(true));
  expect(result.current.checks.createReady).toBe(false);
});

it("gates the form on the binding checks the run found, not the plan's", async () => {
  // Planned with an empty form, the plain sign-in check applies. The run's
  // form picks the scoped sign-in instead, and that check failed.
  startMock.mockResolvedValue(
    run([
      check({ ...BINDING, state: "not_applicable" }),
      check({
        check_id: "scoped_sign_in",
        state: "failed",
        validates_binding: true,
      }),
      CONTENT,
    ])
  );
  const { result } = renderChecks();
  act(() => result.current.checks.begin());

  await waitFor(() => expect(result.current.checks.status).toBe("failed"));
  expect(result.current.checks.formUnlocked).toBe(false);
});

it("unlocks the form without a run when no check validates the binding", async () => {
  planMock.mockResolvedValue(plan([CONTENT]));
  const { result } = renderChecks();

  await waitFor(() => expect(result.current.checks.formUnlocked).toBe(true));
  expect(result.current.checks.createReady).toBe(false);
  expect(startMock).not.toHaveBeenCalled();
});

it("lets Create run without a run when no required check applies", async () => {
  planMock.mockResolvedValue(
    plan([
      check({ check_id: "optional", required: false, state: "pending" }),
      check({ check_id: "sync", state: "not_applicable" }),
    ])
  );
  const { result } = renderChecks();

  await waitFor(() => expect(result.current.checks.createReady).toBe(true));
});

it("ignores non-required failures and unverified checks for Create", async () => {
  startMock.mockResolvedValue(
    run([
      check({ ...BINDING, state: "passed" }),
      check({ ...CONTENT, state: "indeterminate" }),
      check({ check_id: "optional", required: false, state: "failed" }),
    ])
  );
  const { result } = renderChecks();
  act(() => result.current.checks.begin());

  await waitFor(() => expect(result.current.checks.createReady).toBe(true));
  expect(result.current.checks.status).toBe("passed");
});

it("needs a run of the current form before Create", async () => {
  startMock.mockResolvedValue(
    run([
      check({ ...BINDING, state: "passed" }),
      check({ ...CONTENT, state: "passed" }),
    ])
  );
  const { result } = renderChecks();
  act(() => result.current.checks.begin());
  await waitFor(() => expect(result.current.checks.createReady).toBe(true));

  await act(() => result.current.form.setFieldValue("space", "ENG"));
  expect(result.current.checks.createReady).toBe(false);
  expect(result.current.checks.needsRun).toBe(true);

  act(() => result.current.checks.refresh());
  await waitFor(() => expect(result.current.checks.createReady).toBe(true));
  expect(startMock).toHaveBeenCalledTimes(2);
  expect(startMock.mock.calls[1]?.[0].form_state).toEqual({ space: "ENG" });
});

it("reports failedToRun when the start request or the run fails", async () => {
  startMock.mockRejectedValueOnce(new Error("boom"));
  const { result } = renderChecks();
  act(() => result.current.checks.begin());
  await waitFor(() => expect(result.current.checks.status).toBe("failedToRun"));

  startMock.mockResolvedValueOnce(
    run([check({ state: "running" })], "failed_to_run")
  );
  act(() => result.current.checks.rerun());
  await waitFor(() => expect(result.current.checks.status).toBe("failedToRun"));
  expect(result.current.checks.inProgressCount).toBe(0);
  expect(result.current.checks.createReady).toBe(false);
});

it("shares one session between every caller for the source", async () => {
  startMock.mockResolvedValue(run([check({ ...BINDING, state: "passed" })]));
  const { result } = renderHook(
    () => [
      useConnectorChecks({
        source: ValidSources.Confluence,
        credential: refFor(1),
      }),
      useConnectorChecks({
        source: ValidSources.Confluence,
        credential: refFor(1),
      }),
    ],
    { wrapper }
  );

  act(() => result.current[0]!.begin());
  await waitFor(() => expect(result.current[1]!.formUnlocked).toBe(true));
  expect(startMock).toHaveBeenCalledTimes(1);
});
