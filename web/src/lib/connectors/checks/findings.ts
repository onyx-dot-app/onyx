import type {
  CapabilityCheckResult,
  CheckFinding,
  CheckFindingKey,
  FindingOption,
} from "@/lib/connectors/checks/types";
import { configFields } from "@/lib/connectors/checks/formState";
import type { ConnectionConfiguration } from "@/lib/connectors/types";
import type { CredentialCheckReports } from "@/lib/credentials/hooks";

/** Anything that carries findings: a draft check state or a stored result. */
interface WithFindings {
  findings: CheckFinding[];
}

/** The first non-empty options the checks listed under `key`, else empty. */
export function findingOptions(
  checks: readonly WithFindings[],
  key: CheckFindingKey
): FindingOption[] {
  for (const check of checks) {
    for (const finding of check.findings) {
      if (
        finding.type === "options" &&
        finding.key === key &&
        finding.options.length > 0
      ) {
        return finding.options;
      }
    }
  }
  return [];
}

/** The stored reports a form or page may read listings from. */
export interface StoredReportScope {
  credentialId: number;
  /** The pair being edited or shown, whose own report is read first. */
  connectorId: number | null;
}

/** The pair's stored check results, then the credential's own. */
export function storedCheckResults(
  reportFor: CredentialCheckReports["reportFor"],
  scope: StoredReportScope
): CapabilityCheckResult[] {
  const reports = [
    scope.connectorId === null
      ? null
      : reportFor(scope.credentialId, scope.connectorId),
    reportFor(scope.credentialId),
  ];
  return reports.flatMap((report) => report?.report?.check_results ?? []);
}

/** The config with listing-backed entries shown by option label. Entries the listing lacks stay as stored. */
export function labelFindingValues(
  configuration: ConnectionConfiguration,
  config: Record<string, unknown>,
  checks: readonly WithFindings[]
): Record<string, unknown> {
  const labeled: Record<string, unknown> = { ...config };
  for (const field of configFields([
    ...configuration.values,
    ...configuration.advanced_values,
  ])) {
    if (field.type !== "list" || field.optionsFinding === undefined) continue;
    const stored = config[field.name];
    if (!Array.isArray(stored)) continue;
    const labels = new Map(
      findingOptions(checks, field.optionsFinding).map((option) => [
        option.value,
        option.label,
      ])
    );
    labeled[field.name] = stored.map((entry) =>
      typeof entry === "string" ? (labels.get(entry) ?? entry) : entry
    );
  }
  return labeled;
}
