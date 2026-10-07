import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import { Formik } from "formik";
import type { ReactNode } from "react";
import { useConnectorChecks } from "@/lib/connectors/checks/hooks";
import { startDraftCheckRun } from "@/lib/connectors/checks/svc";
import type {
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/connectors/checks/svc", () => ({
  startDraftCheckRun: jest.fn(),
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
// A source with no form fields: the credential alone binds a result.
jest.mock("@/lib/connectors/connectors", () => ({
  useConnectorConfiguration: () => ({ values: [], advanced_values: [] }),
}));
jest.mock("@/lib/connectors/utils", () => ({
  splitCredentialBoundFields: () => ({ values: [], advancedValues: [] }),
}));

const startMock = startDraftCheckRun as jest.MockedFunction<
  typeof startDraftCheckRun
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

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map() }}>
      <Formik initialValues={{}} onSubmit={() => {}}>
        {() => children}
      </Formik>
    </SWRConfig>
  );
}

function renderChecks(credentialId: number | null = 1) {
  return renderHook(
    (props: { credentialId: number | null }) =>
      useConnectorChecks({
        source: ValidSources.Confluence,
        credentialId: props.credentialId,
      }),
    { initialProps: { credentialId }, wrapper }
  );
}

beforeEach(() => startMock.mockReset());

it("runs nothing until begin, and never on its own after that", async () => {
  startMock.mockResolvedValue(run([check({ state: "passed" })]));
  const { result, rerender } = renderChecks();

  expect(result.current.status).toBe("notStarted");
  expect(startMock).not.toHaveBeenCalled();
  act(() => result.current.begin());
  await waitFor(() => expect(result.current.status).toBe("passed"));

  rerender({ credentialId: 2 });
  expect(startMock).toHaveBeenCalledTimes(1);
});

it("turns stale when the credential changes", async () => {
  startMock.mockResolvedValue(run([check({ state: "passed" })]));
  const { result, rerender } = renderChecks();

  act(() => result.current.begin());
  await waitFor(() => expect(result.current.passed).toBe(true));

  rerender({ credentialId: 2 });
  expect(result.current.status).toBe("stale");
  expect(result.current.passed).toBe(false);
});

it("fails while a required check failed, but ignores waiting ones", async () => {
  startMock.mockResolvedValueOnce(
    run([
      check({ state: "failed" }),
      check({ check_id: "w", state: "waiting" }),
    ])
  );
  const { result } = renderChecks();
  act(() => result.current.begin());
  await waitFor(() => expect(result.current.status).toBe("failed"));

  startMock.mockResolvedValueOnce(
    run([
      check({ state: "passed" }),
      check({ check_id: "w", state: "waiting" }),
      check({ check_id: "opt", required: false, state: "failed" }),
    ])
  );
  act(() => result.current.rerun());
  await waitFor(() => expect(result.current.status).toBe("passed"));
});

it("reports failedToRun when the start request or the run fails", async () => {
  startMock.mockRejectedValueOnce(new Error("boom"));
  const { result } = renderChecks();
  act(() => result.current.begin());
  await waitFor(() => expect(result.current.status).toBe("failedToRun"));

  startMock.mockResolvedValueOnce(
    run([check({ state: "running" })], "failed_to_run")
  );
  act(() => result.current.rerun());
  await waitFor(() => expect(result.current.status).toBe("failedToRun"));
  expect(result.current.inProgressCount).toBe(0);
});

it("shares one session between every caller for the source", async () => {
  startMock.mockResolvedValue(run([check({ state: "passed" })]));
  const { result } = renderHook(
    () => [
      useConnectorChecks({ source: ValidSources.Confluence, credentialId: 1 }),
      useConnectorChecks({ source: ValidSources.Confluence, credentialId: 1 }),
    ],
    { wrapper }
  );

  act(() => result.current[0]!.begin());
  await waitFor(() => expect(result.current[1]!.passed).toBe(true));
  expect(startMock).toHaveBeenCalledTimes(1);
});
