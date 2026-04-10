"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { Text, Tag, Card } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgAlertTriangle,
  SvgShield,
} from "@opal/icons";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { useFindings } from "@/app/proposal-review/hooks/useFindings";
import DecisionPanel from "@/app/proposal-review/components/DecisionPanel";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import type {
  Finding,
  FindingsByCategory,
  AuditLogEntry,
} from "@/app/proposal-review/types";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ReviewSidebarProps {
  proposalId: string;
  onDecisionSubmitted: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ReviewSidebar({
  proposalId,
  onDecisionSubmitted,
}: ReviewSidebarProps) {
  const { findings, findingsByCategory } = useFindings(proposalId);

  const { data: auditLog, isLoading: auditLoading } = useSWR<AuditLogEntry[]>(
    `/api/proposal-review/proposals/${proposalId}/audit-log`,
    errorHandlingFetcher
  );

  const stats = useMemo(() => {
    const failCount = findings.filter((f) => f.verdict === "FAIL").length;
    const flagCount = findings.filter((f) => f.verdict === "FLAG").length;
    const passCount = findings.filter((f) => f.verdict === "PASS").length;
    const naCount = findings.filter(
      (f) => f.verdict === "NOT_APPLICABLE"
    ).length;
    const needsReviewCount = findings.filter(
      (f) => f.verdict === "NEEDS_REVIEW"
    ).length;

    const hardStops = findings.filter(
      (f) =>
        f.rule_is_hard_stop && (f.verdict === "FAIL" || f.verdict === "FLAG")
    );

    const unresolvedFindings = findings.filter(
      (f) => (f.verdict === "FAIL" || f.verdict === "FLAG") && !f.decision
    );

    return {
      failCount,
      flagCount,
      passCount,
      naCount,
      needsReviewCount,
      hardStops,
      unresolvedFindings,
      total: findings.length,
    };
  }, [findings]);

  if (findings.length === 0) {
    return (
      <div className="flex items-center justify-center h-full p-4">
        <Text font="secondary-body" color="text-03">
          Run a review to see results here.
        </Text>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4 h-full overflow-y-auto p-4">
      {/* Summary counts */}
      <Card padding="md" border="solid" background="light">
        <div className="flex flex-col gap-2">
          <Text font="main-ui-action" color="text-01">
            Summary
          </Text>
          <div className="grid grid-cols-3 gap-2">
            <SummaryCount
              icon={SvgAlertCircle}
              count={stats.failCount}
              label="Failures"
              iconClass="text-status-error-03"
            />
            <SummaryCount
              icon={SvgAlertTriangle}
              count={stats.flagCount}
              label="Flags"
              iconClass="text-status-warning-03"
            />
            <SummaryCount
              icon={SvgCheckCircle}
              count={stats.passCount}
              label="Passes"
              iconClass="text-status-success-03"
            />
          </div>
        </div>
      </Card>

      {/* Progress by category */}
      <Card padding="md" border="solid" background="light">
        <div className="flex flex-col gap-2">
          <Text font="main-ui-action" color="text-01">
            Progress
          </Text>
          {findingsByCategory.map((group) => (
            <CategoryProgress key={group.category} group={group} />
          ))}
        </div>
      </Card>

      {/* Hard stops */}
      {stats.hardStops.length > 0 && (
        <Card padding="md" border="solid" background="heavy">
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <SvgShield className="h-4 w-4 text-status-error-03" />
              <Text font="main-ui-action" color="text-01">
                {`Hard Stops (${stats.hardStops.length})`}
              </Text>
            </div>
            {stats.hardStops.map((finding) => (
              <div key={finding.id} className="flex items-center gap-2 py-1">
                <Text font="secondary-body" color="text-02">
                  {finding.rule_name ?? "Unnamed Rule"}
                </Text>
                {finding.decision ? (
                  <Tag
                    title={finding.decision.action}
                    color={
                      finding.decision.action === "VERIFIED" ? "green" : "amber"
                    }
                    size="sm"
                  />
                ) : (
                  <Tag title="Unresolved" color="amber" size="sm" />
                )}
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Open flags / unresolved items */}
      {stats.unresolvedFindings.length > 0 && (
        <Card padding="md" border="solid" background="light">
          <div className="flex flex-col gap-2">
            <Text font="main-ui-action" color="text-01">
              {`Unresolved (${stats.unresolvedFindings.length})`}
            </Text>
            {stats.unresolvedFindings.map((finding) => (
              <div
                key={finding.id}
                className="flex items-center gap-2 py-1 px-2 rounded-08 hover:bg-background-neutral-02 cursor-pointer"
              >
                <Tag
                  title={finding.verdict}
                  color={finding.verdict === "FAIL" ? "amber" : "blue"}
                  size="sm"
                />
                <Text font="secondary-body" color="text-02" nowrap>
                  {finding.rule_name ?? "Unnamed Rule"}
                </Text>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Audit trail */}
      <Card padding="md" border="solid" background="light">
        <div className="flex flex-col gap-2">
          <Text font="main-ui-action" color="text-01">
            Audit Trail
          </Text>
          {auditLoading && (
            <div className="flex items-center justify-center py-2">
              <SimpleLoader />
            </div>
          )}
          {!auditLoading && (!auditLog || auditLog.length === 0) && (
            <Text font="secondary-body" color="text-03">
              No activity recorded yet.
            </Text>
          )}
          {auditLog && auditLog.length > 0 && (
            <div className="flex flex-col gap-1 max-h-[200px] overflow-y-auto">
              {[...auditLog]
                .sort(
                  (a, b) =>
                    new Date(b.created_at).getTime() -
                    new Date(a.created_at).getTime()
                )
                .map((entry) => (
                  <AuditEntry key={entry.id} entry={entry} />
                ))}
            </div>
          )}
        </div>
      </Card>

      {/* Decision panel at the bottom */}
      <DecisionPanel
        proposalId={proposalId}
        findings={findings}
        onDecisionSubmitted={onDecisionSubmitted}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Summary count pill
// ---------------------------------------------------------------------------

interface SummaryCountProps {
  icon: React.FunctionComponent<{ className?: string }>;
  count: number;
  label: string;
  iconClass: string;
}

function SummaryCount({
  icon: Icon,
  count,
  label,
  iconClass,
}: SummaryCountProps) {
  return (
    <div className="flex flex-col items-center gap-1 py-2">
      <Icon className={`h-5 w-5 ${iconClass}`} />
      <Text font="main-ui-action" color="text-01">
        {String(count)}
      </Text>
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Category progress row
// ---------------------------------------------------------------------------

interface CategoryProgressProps {
  group: FindingsByCategory;
}

function CategoryProgress({ group }: CategoryProgressProps) {
  const decidedCount = group.findings.filter((f) => f.decision !== null).length;
  const total = group.findings.length;
  const allDone = decidedCount === total;

  return (
    <div className="flex items-center justify-between py-1">
      <Text font="secondary-body" color="text-02" nowrap>
        {group.category}
      </Text>
      <div className="flex items-center gap-1">
        <Text font="secondary-body" color={allDone ? "text-01" : "text-03"}>
          {`${decidedCount}/${total}`}
        </Text>
        {allDone && (
          <SvgCheckCircle className="h-3.5 w-3.5 text-status-success-03" />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Audit log entry
// ---------------------------------------------------------------------------

const AUDIT_ACTION_LABELS: Record<string, string> = {
  review_triggered: "Review triggered",
  finding_decided: "Finding decided",
  decision_submitted: "Decision submitted",
  jira_synced: "Jira synced",
  document_uploaded: "Document uploaded",
};

interface AuditEntryProps {
  entry: AuditLogEntry;
}

function AuditEntry({ entry }: AuditEntryProps) {
  const timestamp = new Date(entry.created_at).toLocaleString();
  const actionLabel = AUDIT_ACTION_LABELS[entry.action] || entry.action;

  return (
    <div className="flex items-start justify-between gap-2 py-1">
      <div className="flex flex-col gap-0.5">
        <Text font="secondary-body" color="text-02">
          {actionLabel}
        </Text>
        {entry.user_id && (
          <Text font="secondary-body" color="text-03">
            {`User: ${entry.user_id.slice(0, 8)}...`}
          </Text>
        )}
      </div>
      <Text font="secondary-body" color="text-03" nowrap>
        {timestamp}
      </Text>
    </div>
  );
}
