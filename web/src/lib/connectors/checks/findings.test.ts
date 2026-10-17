/** Listing-backed config fields: the first non-empty listing wins, stored ids
 * show as their labels, and the pair's report is read before the credential's. */
import {
  findingOptions,
  labelFindingValues,
  storedCheckResults,
} from "@/lib/connectors/checks/findings";
import type {
  CapabilityCheckResult,
  CheckFinding,
} from "@/lib/connectors/checks/types";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { CredentialCheckReport } from "@/lib/credentials/types";

function result(findings: CheckFinding[]): CapabilityCheckResult {
  return {
    capability: "indexing",
    check_id: "listing",
    display_name: "Listing",
    required: false,
    status: "passed",
    message: "",
    remediation: null,
    docs_link: null,
    duration_ms: null,
    findings,
  };
}

function channels(options: { value: string; label: string }[]): CheckFinding {
  return {
    type: "options",
    key: "readable_channels",
    field_name: "channels",
    options: options.map((option) => ({ ...option, detail: null })),
    truncated: false,
  };
}

const GENERAL = { value: "C1", label: "general" };

test("findingOptions skips an empty listing for a later full one", () => {
  const checks = [result([channels([])]), result([channels([GENERAL])])];
  expect(findingOptions(checks, "readable_channels")).toEqual([
    { ...GENERAL, detail: null },
  ]);
  expect(findingOptions(checks, "shared_drives")).toEqual([]);
});

test("labelFindingValues shows ids by label and leaves the rest", () => {
  const configuration: ConnectionConfiguration = {
    description: "",
    values: [],
    advanced_values: [
      {
        type: "tab",
        name: "mode",
        tabs: [
          {
            label: "Channels",
            value: "channels",
            fields: [
              {
                type: "list",
                label: "Channels",
                name: "channels",
                optionsFinding: "readable_channels",
              },
            ],
          },
        ],
      },
      { type: "list", label: "Patterns", name: "patterns" },
    ],
  };
  const labeled = labelFindingValues(
    configuration,
    { channels: ["C1", "typed-name"], patterns: ["C1"], flag: true },
    [result([channels([GENERAL])])]
  );
  expect(labeled).toEqual({
    channels: ["general", "typed-name"],
    patterns: ["C1"],
    flag: true,
  });
});

test("storedCheckResults reads the pair's report before the credential's", () => {
  const report = (
    connectorId: number | null,
    label: string
  ): CredentialCheckReport => ({
    credential_id: 7,
    connector_id: connectorId,
    run_status: "completed",
    run_started_at: null,
    report: {
      checked_at: "2026-10-13T00:00:00Z",
      check_results: [result([channels([{ value: "C1", label }])])],
    },
    time_updated: "2026-10-13T00:00:00Z",
  });
  const reports = [report(3, "from-pair"), report(null, "from-credential")];
  const reportFor = (credentialId: number, connectorId: number | null = null) =>
    reports.find(
      (candidate) =>
        candidate.credential_id === credentialId &&
        candidate.connector_id === connectorId
    ) ?? null;

  const labels = (connectorId: number | null) =>
    findingOptions(
      storedCheckResults(reportFor, { credentialId: 7, connectorId }),
      "readable_channels"
    ).map((option) => option.label);
  expect(labels(3)).toEqual(["from-pair"]);
  expect(labels(null)).toEqual(["from-credential"]);
  expect(labels(9)).toEqual(["from-credential"]);
});
