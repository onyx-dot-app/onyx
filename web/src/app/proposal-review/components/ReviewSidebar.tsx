"use client";

import { useMemo } from "react";
import { Text, Tag, Card } from "@opal/components";
import {
  SvgAlertCircle,
  SvgCheckCircle,
  SvgAlertTriangle,
  SvgShield,
} from "@opal/icons";
import { cn } from "@/lib/utils";
import { Section } from "@/layouts/general-layouts";
import { useFindings } from "@/app/proposal-review/hooks/useFindings";
import { useProposalReviewContext } from "@/app/proposal-review/contexts/ProposalReviewContext";
import DecisionPanel from "@/app/proposal-review/components/DecisionPanel";
import {
  VERDICT_CONFIG,
  type Finding,
  type FindingsByCategory,
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
  const { viewingRunId, setFocusedFindingId } = useProposalReviewContext();
  const { findings, findingsByCategory } = useFindings(
    proposalId,
    false,
    viewingRunId
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

    // Derive unresolved from findingsByCategory so they appear in the
    // same category-sorted order as the main checklist panel.
    const unresolvedFindings = findingsByCategory.flatMap((group) =>
      group.findings.filter(
        (f) =>
          (f.verdict === "FAIL" || f.verdict === "FLAG") && !f.decision_action
      )
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
  }, [findings, findingsByCategory]);

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
        <Section
          gap={0.5}
          height="auto"
          justifyContent="start"
          alignItems="start"
        >
          <Text font="main-ui-action" color="text-04">
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
        </Section>
      </Card>

      {/* Progress by category */}
      <Card padding="md" border="solid" background="light">
        <Section
          gap={0.5}
          height="auto"
          justifyContent="start"
          alignItems="start"
        >
          <Text font="main-ui-action" color="text-04">
            Progress
          </Text>
          {findingsByCategory.map((group) => (
            <CategoryProgress key={group.category} group={group} />
          ))}
        </Section>
      </Card>

      {/* Hard stops */}
      {stats.hardStops.length > 0 && (
        <Card padding="md" border="solid" background="heavy">
          <Section
            gap={0.5}
            height="auto"
            justifyContent="start"
            alignItems="start"
          >
            <Section
              flexDirection="row"
              gap={0.5}
              height="auto"
              justifyContent="start"
              alignItems="center"
            >
              <SvgShield className="h-4 w-4 text-status-error-03" />
              <Text font="main-ui-action" color="text-04">
                {`Hard Stops (${stats.hardStops.length})`}
              </Text>
            </Section>
            {stats.hardStops.map((finding) => (
              <div
                key={finding.id}
                role="button"
                tabIndex={0}
                className="flex items-center gap-2 py-1 px-2 w-full overflow-hidden rounded-08 hover:bg-background-neutral-02 cursor-pointer"
                onClick={() => setFocusedFindingId(finding.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setFocusedFindingId(finding.id);
                  }
                }}
              >
                <div className="min-w-0 truncate">
                  <Text font="secondary-body" color="text-03">
                    {finding.rule_name ?? "Unnamed Rule"}
                  </Text>
                </div>
                <div className="shrink-0">
                  {finding.decision_action ? (
                    <Tag
                      title={finding.decision_action}
                      color={
                        finding.decision_action === "VERIFIED"
                          ? "green"
                          : "amber"
                      }
                      size="sm"
                    />
                  ) : (
                    <Tag title="Unresolved" color="amber" size="sm" />
                  )}
                </div>
              </div>
            ))}
          </Section>
        </Card>
      )}

      {/* Open flags / unresolved items */}
      {stats.unresolvedFindings.length > 0 && (
        <Card padding="md" border="solid" background="light">
          <Section
            gap={0.5}
            height="auto"
            justifyContent="start"
            alignItems="start"
          >
            <Text font="main-ui-action" color="text-04">
              {`Unresolved (${stats.unresolvedFindings.length})`}
            </Text>
            {stats.unresolvedFindings.map((finding) => (
              <div
                key={finding.id}
                role="button"
                tabIndex={0}
                className="flex items-center gap-2 py-1 px-2 w-full overflow-hidden rounded-08 hover:bg-background-neutral-02 cursor-pointer"
                onClick={() => setFocusedFindingId(finding.id)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setFocusedFindingId(finding.id);
                  }
                }}
              >
                <div className="shrink-0">
                  <Tag
                    title={VERDICT_CONFIG[finding.verdict].label}
                    color={VERDICT_CONFIG[finding.verdict].color}
                    size="sm"
                  />
                </div>
                <div className="min-w-0 truncate">
                  <Text font="secondary-body" color="text-03">
                    {finding.rule_name ?? "Unnamed Rule"}
                  </Text>
                </div>
              </div>
            ))}
          </Section>
        </Card>
      )}

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
    <Section
      gap={0.25}
      height="auto"
      padding={0.5}
      alignItems="center"
      justifyContent="center"
    >
      <Icon className={cn("h-5 w-5", iconClass)} />
      <Text font="main-ui-action" color="text-04">
        {String(count)}
      </Text>
      <Text font="secondary-body" color="text-03">
        {label}
      </Text>
    </Section>
  );
}

// ---------------------------------------------------------------------------
// Category progress row
// ---------------------------------------------------------------------------

interface CategoryProgressProps {
  group: FindingsByCategory;
}

function CategoryProgress({ group }: CategoryProgressProps) {
  const decidedCount = group.findings.filter(
    (f) => f.decision_action !== null
  ).length;
  const total = group.findings.length;
  const allDone = decidedCount === total;

  return (
    <div className="flex items-center justify-between gap-2 py-1 w-full overflow-hidden">
      <div className="min-w-0 truncate">
        <Text font="secondary-body" color="text-03">
          {group.category}
        </Text>
      </div>
      <div className="flex items-center gap-1 shrink-0">
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
