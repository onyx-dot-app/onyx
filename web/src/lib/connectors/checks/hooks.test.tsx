import { act, renderHook, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";
import { useDraftCheckRun } from "@/lib/connectors/checks/hooks";
import { startDraftCheckRun } from "@/lib/connectors/checks/svc";
import type {
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";
import { ValidSources } from "@/lib/connectors/types/source";

jest.mock("@/lib/connectors/checks/svc", () => ({
  startDraftCheckRun: jest.fn(),
}));
// The run is seeded from the start response, so polling never fetches.
jest.mock("@/lib/fetcher", () => ({ errorHandlingFetcher: jest.fn() }));

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

function run(checks: DraftCheckState[]): DraftCheckRunSnapshot {
  return {
    run_id: "run-1",
    draft_key: "draft",
    source: ValidSources.Confluence,
    credential_id: 1,
    access_type: "public",
    status: "completed",
    form_errors: {},
    unknown_fields: [],
    checks,
  };
}

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
  );
}

function renderRun(initial: { bindingKey: string; formState?: object }) {
  return renderHook(
    (props: { bindingKey: string; formState?: object }) =>
      useDraftCheckRun({
        source: ValidSources.Confluence,
        credentialId: 1,
        accessType: "public",
        formState: { ...props.formState },
        bindingKey: props.bindingKey,
      }),
    { initialProps: initial, wrapper }
  );
}

beforeEach(() => startMock.mockReset());

it("runs nothing until begin, and never on its own after that", async () => {
  startMock.mockResolvedValue(run([check({ state: "passed" })]));
  const { result, rerender } = renderRun({ bindingKey: "a" });

  expect(startMock).not.toHaveBeenCalled();
  act(() => result.current.begin());
  await waitFor(() => expect(result.current.passed).toBe(true));

  rerender({ bindingKey: "a", formState: { space: "ENG" } });
  rerender({ bindingKey: "b" });
  expect(startMock).toHaveBeenCalledTimes(1);
});

it("stops passing when the credential configuration changes", async () => {
  startMock.mockResolvedValue(run([check({ state: "passed" })]));
  const { result, rerender } = renderRun({ bindingKey: "a" });

  act(() => result.current.begin());
  await waitFor(() => expect(result.current.passed).toBe(true));

  rerender({ bindingKey: "b" });
  expect(result.current.stale).toBe(true);
  expect(result.current.passed).toBe(false);
});

it("does not pass while a required check failed, but ignores waiting ones", async () => {
  startMock.mockResolvedValueOnce(
    run([
      check({ state: "failed" }),
      check({ check_id: "w", state: "waiting" }),
    ])
  );
  const { result } = renderRun({ bindingKey: "a" });
  act(() => result.current.begin());
  await waitFor(() => expect(result.current.snapshot).not.toBeNull());
  expect(result.current.passed).toBe(false);

  startMock.mockResolvedValueOnce(
    run([
      check({ state: "passed" }),
      check({ check_id: "w", state: "waiting" }),
      check({ check_id: "opt", required: false, state: "failed" }),
    ])
  );
  act(() => result.current.rerun());
  await waitFor(() => expect(result.current.passed).toBe(true));
});
