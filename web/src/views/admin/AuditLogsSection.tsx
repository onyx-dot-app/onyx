"use client";

import { useFormatter, useTranslations } from "next-intl";
import useSWR from "swr";
import { Card, InputSwitch, MessageCard } from "@opal/components";
import { Content, InputHorizontal, Section } from "@opal/layouts";
import { LineLoader } from "@opal/loaders";
import { markdown } from "@opal/utils";
import { DOCS_ADMINS_PATH } from "@/lib/constants";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { usePlans, useTierAtLeast } from "@/lib/tiers/hooks";
import { Tier } from "@/lib/tiers/types";
import type {
  AuditClassStatus,
  AuditEventCategory,
  AuditStreamStatus,
  SecuritySettings,
} from "@/lib/types";

const AUDIT_DOCS_URL = `${DOCS_ADMINS_PATH}/auditing/audit_logs`;

// The order the switches show in. Must list every AuditEventCategory.
const AUDIT_CATEGORIES: AuditEventCategory[] = [
  "authentication",
  "user_and_group_management",
  "configuration",
  "credential_access",
  "data_export",
];
const ACTIVITY_CATEGORIES: AuditEventCategory[] = [
  "chat",
  "search",
  "llm_gateway",
  "file_download",
];
const ALL_CATEGORIES = [...AUDIT_CATEGORIES, ...ACTIVITY_CATEGORIES];

type AuditSettingsUpdate = Partial<
  Pick<SecuritySettings, "audit_event_categories" | "audit_include_query_text">
>;

interface AuditLogsSectionProps {
  categories: AuditEventCategory[];
  includeQueryText: boolean;
  onSave: (updates: AuditSettingsUpdate) => void;
}

export default function AuditLogsSection({
  categories,
  includeQueryText,
  onSave,
}: AuditLogsSectionProps) {
  const t = useTranslations("admin.security.auditLogs");
  const enterpriseTier = useTierAtLeast(Tier.ENTERPRISE);
  const plans = usePlans();

  function setCategory(category: AuditEventCategory, enabled: boolean) {
    onSave({
      audit_event_categories: ALL_CATEGORIES.filter((each) =>
        each === category ? enabled : categories.includes(each)
      ),
    });
  }

  function categorySwitches(group: AuditEventCategory[]) {
    return group.map((category) => (
      <InputHorizontal
        key={category}
        title={t(`categories.${category}.title`)}
        description={t(`categories.${category}.description`)}
        withLabel
      >
        <InputSwitch
          checked={categories.includes(category)}
          onCheckedChange={(checked) => setCategory(category, checked)}
        />
      </InputHorizontal>
    ));
  }

  return (
    <Section gap={3} alignItems="stretch" justifyContent="start" height="auto">
      <Content
        font="main-content-emphasis"
        title={t("section.title")}
        description={markdown(
          t("section.description", { url: AUDIT_DOCS_URL })
        )}
        badge={enterpriseTier ? undefined : plans[Tier.ENTERPRISE].tag}
      />

      {enterpriseTier && (
        <>
          <AuditStreamStatusCard />

          <Card border="solid" rounding={4}>
            <Section>
              <Content
                font="main-ui-action"
                title={t("auditEvents.title")}
                description={t("auditEvents.description")}
              />
              {categorySwitches(AUDIT_CATEGORIES)}
            </Section>
          </Card>

          <Card border="solid" rounding={4}>
            <Section>
              <Content
                font="main-ui-action"
                title={t("userActivity.title")}
                description={t("userActivity.description")}
              />
              {categorySwitches(ACTIVITY_CATEGORIES)}
              <InputHorizontal
                title={t("queryText.title")}
                description={t("queryText.description")}
                withLabel
              >
                <InputSwitch
                  checked={includeQueryText}
                  onCheckedChange={(checked) =>
                    onSave({ audit_include_query_text: checked })
                  }
                />
              </InputHorizontal>
            </Section>
          </Card>
        </>
      )}
    </Section>
  );
}

function AuditStreamStatusCard() {
  const t = useTranslations("admin.security.auditLogs");
  const format = useFormatter();
  const { data: status, error } = useSWR<AuditStreamStatus>(
    SWR_KEYS.adminAuditStatus,
    errorHandlingFetcher
  );

  // The count and the last event time are separate cache entries, so either
  // can be present without the other.
  function classSummary(entry: AuditClassStatus): string {
    if (entry.last_event_at !== null) {
      return t("status.eventSummary", {
        count: entry.events_last_24h,
        lastEvent: format.relativeTime(new Date(entry.last_event_at)),
      });
    }
    if (entry.events_last_24h > 0) {
      return t("status.eventCount", { count: entry.events_last_24h });
    }
    return t("status.noEvents");
  }

  if (error) {
    return (
      <MessageCard
        variant="error"
        title={t("status.loadFailed.title")}
        description={t("status.loadFailed.description")}
      />
    );
  }

  return (
    <Card border="solid" rounding={4}>
      <Section>
        <Content
          font="main-ui-action"
          title={t("status.title")}
          description={t("status.description")}
        />
        {!status ? (
          <LineLoader lines={3} width="2/3" />
        ) : (
          <>
            {!status.enabled && (
              <MessageCard
                variant="warning"
                title={t("status.notEnabled.title")}
                description={t("status.notEnabled.description")}
              />
            )}
            {status.log_format !== "json" && (
              <MessageCard
                variant="warning"
                title={t("status.logFormat.title")}
                description={t("status.logFormat.description", {
                  logFormat: status.log_format,
                })}
              />
            )}
            {status.classes.map((entry) => (
              <Content
                key={entry.event_class}
                title={t(`status.classes.${entry.event_class}`)}
                description={classSummary(entry)}
              />
            ))}
          </>
        )}
      </Section>
    </Card>
  );
}
