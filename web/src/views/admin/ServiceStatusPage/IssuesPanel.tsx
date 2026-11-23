"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  Divider,
  MessageCard,
  Tag,
  Text,
} from "@opal/components";
import { Section } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import {
  SvgAlertCircle,
  SvgAlertTriangle,
  SvgExternalLink,
  SvgSearchMenu,
  SvgX,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import type {
  ClusterIssue,
  ClusterIssueKind,
} from "@/lib/service-status/types";
import { useClusterStatus } from "@/lib/service-status/hooks";
import { SIZING_GUIDE_URL } from "@/views/admin/ServiceStatusPage/format";

const DISMISSED_KEY = "onyx.serviceStatus.dismissedIssues";

// Kinds whose fix is on Index Settings: a smaller vector quantization, or a
// new index.
const INDEX_SETTINGS_KINDS: ReadonlySet<ClusterIssueKind> = new Set([
  "vector_memory",
  "index_missing",
]);

// Kinds that more storage or memory does not fix.
const NO_SIZING_GUIDE_KINDS: ReadonlySet<ClusterIssueKind> = new Set([
  "index_missing",
  "nodes_unanswered",
]);

const ISSUE_MESSAGES = {
  cluster_red: {
    critical: ["clusterRed.title", "clusterRed.description"],
    warning: ["clusterRed.title", "clusterRed.description"],
  },
  unassigned_shards: {
    critical: ["unassignedShards.title", "unassignedShards.description"],
    warning: ["unassignedShards.title", "unassignedShards.description"],
  },
  disk: {
    critical: ["diskCritical.title", "diskCritical.description"],
    warning: ["diskWarning.title", "diskWarning.description"],
  },
  vector_memory: {
    critical: ["vectorCritical.title", "vectorCritical.description"],
    warning: ["vectorWarning.title", "vectorWarning.description"],
  },
  jvm_memory: {
    critical: ["heap.title", "heap.description"],
    warning: ["heap.title", "heap.description"],
  },
  index_missing: {
    critical: ["indexMissing.title", "indexMissing.description"],
    warning: ["indexMissing.title", "indexMissing.description"],
  },
  nodes_unanswered: {
    critical: ["nodesUnanswered.title", "nodesUnanswered.description"],
    warning: ["nodesUnanswered.title", "nodesUnanswered.description"],
  },
} as const;

/** Changes when the issue's nodes or rounded value change, so it shows again. */
function issueId(issue: ClusterIssue): string {
  return [
    issue.kind,
    issue.severity,
    ...issue.node_names,
    Math.round(issue.value),
  ].join(":");
}

function readDismissed(): Set<string> {
  try {
    const raw = window.localStorage.getItem(DISMISSED_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return new Set(
      Array.isArray(parsed)
        ? parsed.filter((item): item is string => typeof item === "string")
        : []
    );
  } catch {
    return new Set();
  }
}

function writeDismissed(ids: Set<string>) {
  try {
    window.localStorage.setItem(DISMISSED_KEY, JSON.stringify([...ids]));
  } catch {
    // Storage can be unavailable; dismissal then lasts until reload.
  }
}

interface IssueCardProps {
  issue: ClusterIssue;
  onDismiss?: () => void;
}

function IssueCard({ issue, onDismiss }: IssueCardProps) {
  const t = useTranslations("admin.serviceStatus.issues");
  const navigation = useNavigation();
  const nodes =
    issue.node_names.length === 1
      ? (issue.node_names[0] ?? "")
      : t("nodeCount", { count: issue.node_names.length });
  const values = { value: Math.round(issue.value), nodes };
  const [titleKey, descriptionKey] = ISSUE_MESSAGES[issue.kind][issue.severity];

  return (
    <MessageCard
      variant={issue.severity === "critical" ? "error" : "warning"}
      icon={issue.severity === "critical" ? SvgAlertTriangle : SvgAlertCircle}
      title={t(titleKey, values)}
      description={t(descriptionKey, values)}
      bottomChildren={
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          width="full"
        >
          <Section flexDirection="row" gap={0.5} width="fit">
            {INDEX_SETTINGS_KINDS.has(issue.kind) && (
              <Tag
                title={t("indexSettings")}
                icon={SvgSearchMenu}
                onClick={() => navigation.go(ADMIN_ROUTES.INDEX_SETTINGS.path)}
              />
            )}
            {!NO_SIZING_GUIDE_KINDS.has(issue.kind) && (
              <Tag
                title={t("sizingGuide")}
                icon={SvgExternalLink}
                onClick={() =>
                  window.open(SIZING_GUIDE_URL, "_blank", "noopener,noreferrer")
                }
              />
            )}
          </Section>
          {onDismiss && (
            <Button
              prominence="tertiary"
              size="sm"
              rightIcon={SvgX}
              onClick={onDismiss}
            >
              {t("dismiss")}
            </Button>
          )}
        </Section>
      }
    />
  );
}

interface CountProps {
  icon: IconFunctionComponent;
  count: number;
  className: string;
}

function Count({ icon: Icon, count, className }: CountProps) {
  return (
    <Section flexDirection="row" gap={0.25} alignItems="center" width="fit">
      <Icon size={14} className={className} />
      <Text as="p" font="secondary-body" color="text-03">
        {String(count)}
      </Text>
    </Section>
  );
}

interface IssueListProps {
  issues: ClusterIssue[];
}

function IssueList({ issues }: IssueListProps) {
  const t = useTranslations("admin.serviceStatus.issues");
  const [dismissed, setDismissed] = useState<Set<string>>(new Set());

  useEffect(() => {
    setDismissed(readDismissed());
  }, []);

  const critical = issues.filter((issue) => issue.severity === "critical");
  const warnings = issues.filter(
    (issue) => issue.severity === "warning" && !dismissed.has(issueId(issue))
  );

  function dismiss(issue: ClusterIssue) {
    const next = new Set(dismissed);
    next.add(issueId(issue));
    setDismissed(next);
    writeDismissed(next);
  }

  return (
    <Card
      border="solid"
      rounding={4}
      padding={3}
      data-testid="service-status-issues"
    >
      <Section gap={1} alignItems="stretch" width="full">
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="center"
          width="full"
        >
          <Section
            flexDirection="row"
            gap={0.5}
            alignItems="center"
            width="fit"
          >
            <SvgAlertCircle size={16} className="text-text-04" />
            <Text font="main-ui-action" color="text-04" as="h3">
              {t("title")}
            </Text>
          </Section>
          <Section
            flexDirection="row"
            gap={0.75}
            alignItems="center"
            width="fit"
          >
            {critical.length > 0 && (
              <Count
                icon={SvgAlertTriangle}
                count={critical.length}
                className="text-status-error-05"
              />
            )}
            {warnings.length > 0 && (
              <Count
                icon={SvgAlertCircle}
                count={warnings.length}
                className="text-status-warning-05"
              />
            )}
          </Section>
        </Section>
        {critical.length === 0 && warnings.length === 0 && (
          <Text as="p" font="secondary-body" color="text-03">
            {t("none")}
          </Text>
        )}
        {critical.length > 0 && (
          <Section gap={0.5} alignItems="stretch" width="full">
            <Divider title={t("criticalCount", { count: critical.length })} />
            {critical.map((issue) => (
              <IssueCard key={issueId(issue)} issue={issue} />
            ))}
          </Section>
        )}
        {warnings.length > 0 && (
          <Section gap={0.5} alignItems="stretch" width="full">
            <Divider title={t("warningCount", { count: warnings.length })} />
            {warnings.map((issue) => (
              <IssueCard
                key={issueId(issue)}
                issue={issue}
                onDismiss={() => dismiss(issue)}
              />
            ))}
          </Section>
        )}
      </Section>
    </Card>
  );
}

/** Whether any issue shows: every critical one and the undismissed warnings. */
export function hasVisibleIssues(issues: ClusterIssue[]): boolean {
  const dismissed = readDismissed();
  return issues.some(
    (issue) => issue.severity === "critical" || !dismissed.has(issueId(issue))
  );
}

export default function IssuesPanel() {
  const { data } = useClusterStatus();
  // The page shows the loader until the first read.
  return data ? <IssueList issues={data.issues} /> : null;
}
