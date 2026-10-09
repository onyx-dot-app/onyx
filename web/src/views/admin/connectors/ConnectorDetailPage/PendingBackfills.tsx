"use client";

import { windowCoversAllHistory } from "@/lib/connectors/edit/window";
import { useFormatter, useTranslations } from "next-intl";
import { Card, Tag, Text } from "@opal/components";
import { Content, ContentAction, Section } from "@opal/layouts";
import { SvgHistory } from "@opal/icons";
import type { PendingBackfillSnapshot } from "@/lib/connectors/types";

export interface PendingBackfillsProps {
  backfills: PendingBackfillSnapshot[];
}

/** The backfills that applied edits requested and that have not succeeded. */
export default function PendingBackfills({ backfills }: PendingBackfillsProps) {
  const t = useTranslations("admin.connectorEdit.pendingBackfills");
  const format = useFormatter();
  const dateTime = (value: string) =>
    format.dateTime(new Date(value), {
      dateStyle: "medium",
      timeStyle: "short",
    });

  return (
    <Card border="solid" padding={4} rounding={3}>
      <Section gap={2} alignItems="stretch" height="fit">
        <Content
          icon={SvgHistory}
          title={t("title")}
          description={t("description")}
          sizePreset="main-ui"
          variant="section"
        />
        {backfills.map((backfill) => (
          <ContentAction
            key={`${backfill.window_start}-${backfill.requested_at}`}
            title={
              windowCoversAllHistory(backfill.window_start)
                ? t("windowFromStart", { end: dateTime(backfill.window_end) })
                : t("window", {
                    start: dateTime(backfill.window_start),
                    end: dateTime(backfill.window_end),
                  })
            }
            description={
              backfill.retry_after === null
                ? t("waiting")
                : t("retry", {
                    count: backfill.failure_count,
                    time: dateTime(backfill.retry_after),
                  })
            }
            sizePreset="main-ui"
            variant="section"
            rightChildren={
              <Section flexDirection="row" gap={1} height="fit" width="fit">
                {backfill.scoped && <Tag title={t("scoped")} color="blue" />}
                {backfill.failure_count > 0 && (
                  <Tag
                    title={t("failures", { count: backfill.failure_count })}
                    color="amber"
                  />
                )}
              </Section>
            }
          />
        ))}
        {backfills.some((backfill) => backfill.attempt_id !== null) && (
          <Text font="secondary-body" color="text-03">
            {t("running")}
          </Text>
        )}
      </Section>
    </Card>
  );
}
