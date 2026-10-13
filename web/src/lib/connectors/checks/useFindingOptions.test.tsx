/** The listing a picker offers follows the form's account: the account's own
 * run first, else its stored report, never another account's run. */
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { SWRConfig, useSWRConfig } from "swr";
import { useFindingOptions } from "@/lib/connectors/checks/hooks";
import type { StoredReportScope } from "@/lib/connectors/checks/findings";
import type {
  CapabilityCheckResult,
  CheckFinding,
  DraftCheckRunSnapshot,
  DraftCheckState,
} from "@/lib/connectors/checks/types";
import { ValidSources } from "@/lib/connectors/types/source";
import type { CredentialCheckReport } from "@/lib/credentials/types";
import { SWR_KEYS } from "@/lib/swr-keys";

const SOURCE = ValidSources.Slack;

function listing(label: string): CheckFinding {
  return {
    type: "options",
    key: "readable_channels",
    field_name: "channels",
    options: [{ value: "C1", label, detail: null }],
    truncated: false,
  };
}

function checkState(findings: CheckFinding[]): DraftCheckState {
  return {
    check_id: "listing",
    display_name: "Listing",
    capability: "indexing",
    required: false,
    state: "passed",
    message: "",
    missing_fields: [],
    invalid_fields: [],
    remediation: null,
    docs_link: null,
    duration_ms: 1,
    from_cache: false,
    validates_binding: false,
    findings,
  };
}

function checkResult(findings: CheckFinding[]): CapabilityCheckResult {
  return {
    capability: "indexing",
    check_id: "listing",
    display_name: "Listing",
    required: false,
    status: "passed",
    message: "",
    remediation: null,
    docs_link: null,
    duration_ms: 1,
    findings,
  };
}

function report(credentialId: number, label: string): CredentialCheckReport {
  return {
    credential_id: credentialId,
    connector_id: null,
    run_status: "completed",
    run_started_at: null,
    report: {
      checked_at: "2026-10-13T00:00:00Z",
      check_results: [checkResult([listing(label)])],
    },
    time_updated: "2026-10-13T00:00:00Z",
  };
}

const REPORTS: CredentialCheckReport[] = [
  report(1, "from-report-1"),
  report(2, "from-report-2"),
];

jest.mock("@/lib/credentials/hooks", () => ({
  useCredentialCheckReports: () => ({
    reportFor: (credentialId: number, connectorId: number | null = null) =>
      REPORTS.find(
        (candidate) =>
          candidate.credential_id === credentialId &&
          candidate.connector_id === connectorId
      ) ?? null,
    rerun: async () => undefined,
  }),
  useSavedDraftCredential: () => ({
    savedDraft: null,
    rememberDraft: async () => undefined,
  }),
}));

const RUN: DraftCheckRunSnapshot = {
  run_id: "run-1",
  draft_key: "draft",
  source: SOURCE,
  credential_id: 1,
  access_type: "public",
  status: "completed",
  form_errors: {},
  unknown_fields: [],
  checks: [checkState([listing("from-run-1")])],
};

function wrapper({ children }: { children: ReactNode }) {
  return (
    <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>
  );
}

function scopeFor(credentialId: number): StoredReportScope {
  return { credentialId, connectorId: null };
}

test("the account's run wins, and another account's run is ignored", async () => {
  const { result, rerender } = renderHook(
    (props: { scope: StoredReportScope }) => ({
      labels: useFindingOptions(SOURCE, "readable_channels", props.scope).map(
        (option) => option.label
      ),
      swr: useSWRConfig(),
    }),
    { initialProps: { scope: scopeFor(1) }, wrapper }
  );
  expect(result.current.labels).toEqual(["from-report-1"]);

  // A run of account 1 seeds the session and run keys as a check start does.
  await act(async () => {
    await result.current.swr.mutate(
      SWR_KEYS.connectorCheckSession(SOURCE),
      { runId: RUN.run_id },
      { revalidate: false }
    );
    await result.current.swr.mutate(
      SWR_KEYS.connectorCheckRun(RUN.run_id),
      RUN,
      { revalidate: false }
    );
  });
  expect(result.current.labels).toEqual(["from-run-1"]);

  // Switching to account 2 before the session resets reads its own report.
  rerender({ scope: scopeFor(2) });
  expect(result.current.labels).toEqual(["from-report-2"]);
});
