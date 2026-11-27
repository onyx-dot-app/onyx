"use client";

import { useTranslations } from "next-intl";
import {
  Badge,
  Card,
  EmptyMessageCard,
  MessageCard,
  Text,
} from "@opal/components";
import { Section, SettingsLayouts } from "@opal/layouts";
import { ADMIN_ROUTES } from "@/lib/admin-routes";
import { useAdminRouteTitle } from "@/lib/adminNavLabels";
import { useSandboxStatus } from "@/lib/sandbox-status/hooks";
import type {
  SandboxNodeStatus,
  SandboxStatus,
  SandboxToolsOffReason,
} from "@/lib/sandbox-status/types";

const route = ADMIN_ROUTES.SANDBOX_STATUS;

function useOffReasonText(): (reason: SandboxToolsOffReason) => string {
  const t = useTranslations("admin.sandboxStatus.reasons");
  return (reason) => {
    switch (reason) {
      case "RUNTIME_WITHOUT_FIRECRACKER":
        return t("runtimeWithoutFirecracker");
      case "TEMPLATE_NOT_CONFIGURED":
        return t("templateNotConfigured");
      case "NO_REGISTERED_NODE":
        return t("noRegisteredNode");
      case "NO_LIVE_NODE_WITH_TEMPLATE":
        return t("noLiveNodeWithTemplate");
      case "NODE_STATE_UNREADABLE":
        return t("nodeStateUnreadable");
    }
  };
}

interface SummaryCardProps {
  status: SandboxStatus;
}

function SummaryCard({ status }: SummaryCardProps) {
  const t = useTranslations("admin.sandboxStatus.summary");
  const offReasonText = useOffReasonText();
  return (
    <MessageCard
      variant={status.tools_offered ? "success" : "warning"}
      title={status.tools_offered ? t("toolsOffered") : t("toolsOff")}
      description={
        status.tools_off_reason
          ? offReasonText(status.tools_off_reason)
          : status.runtime === "auto"
            ? t("toolsOfferedDescription")
            : t("toolsOfferedAlwaysDescription")
      }
      bottomChildren={
        <Section gap={0.25} alignItems="start" width="full">
          <Text as="p" font="secondary-body" color="text-03">
            {t("runtime", { runtime: status.runtime })}
          </Text>
          <Text as="p" font="secondary-body" color="text-03">
            {status.template
              ? t("template", { template: status.template })
              : t("noTemplate")}
          </Text>
        </Section>
      }
    />
  );
}

interface NodeCardProps {
  node: SandboxNodeStatus;
}

function NodeCard({ node }: NodeCardProps) {
  const t = useTranslations("admin.sandboxStatus.nodes");
  return (
    <Card
      border="solid"
      rounding={4}
      padding={3}
      data-testid="sandbox-status-node"
    >
      <Section gap={0.5} alignItems="start" width="full">
        <Section
          flexDirection="row"
          gap={0.5}
          alignItems="center"
          width="full"
          wrap
        >
          <Text
            as="p"
            font="main-ui-action"
            color="text-04"
            maxLines={1}
            overflowTooltip
          >
            {node.node_id}
          </Text>
          <Badge
            title={node.live ? t("live") : t("stale")}
            color={node.live ? "success" : "error"}
          />
          {node.draining && <Badge title={t("draining")} color="warning" />}
          <Badge
            title={node.has_template ? t("hasTemplate") : t("noTemplate")}
            color={node.has_template ? "success" : "warning"}
          />
        </Section>
        <Text as="p" font="secondary-body" color="text-03">
          {node.last_report_age_seconds === null
            ? t("neverReported")
            : t("lastReport", { seconds: node.last_report_age_seconds })}
        </Text>
        {node.agent_version !== null && (
          <Text as="p" font="secondary-body" color="text-03">
            {t("agentVersion", { version: node.agent_version })}
          </Text>
        )}
        {node.vm_count !== null && (
          <Text as="p" font="secondary-body" color="text-03">
            {node.max_vms
              ? t("vmsOfCap", { count: node.vm_count, cap: node.max_vms })
              : t("vms", { count: node.vm_count })}
          </Text>
        )}
        <Text as="p" font="secondary-body" color="text-03">
          {node.templates.length
            ? t("templates", { templates: node.templates.join(", ") })
            : t("noTemplates")}
        </Text>
      </Section>
    </Card>
  );
}

export default function SandboxStatusPage() {
  const t = useTranslations("admin.sandboxStatus");
  const adminRouteTitle = useAdminRouteTitle();
  const { data, error } = useSandboxStatus();

  return (
    <SettingsLayouts.Root
      loading={!data && !error}
      // A failed background read keeps the last status on the page.
      error={error && !data ? t("page.loadFailed") : false}
    >
      <SettingsLayouts.Header
        icon={route.icon}
        title={adminRouteTitle(route)}
        description={t("page.description")}
        divider
      />
      <SettingsLayouts.Body>
        {data && (
          <Section gap={2} alignItems="stretch" width="full">
            {error && (
              <MessageCard
                variant="error"
                title={t("page.refreshFailed")}
                description={t("page.refreshFailedDescription")}
              />
            )}
            <SummaryCard status={data} />
            <Section gap={1} alignItems="stretch" width="full">
              <Text as="p" font="main-ui-action" color="text-04">
                {t("nodes.title")}
              </Text>
              {data.nodes.length ? (
                data.nodes.map((node) => (
                  <NodeCard key={node.node_id} node={node} />
                ))
              ) : (
                <EmptyMessageCard title={t("nodes.empty")} />
              )}
            </Section>
          </Section>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}
