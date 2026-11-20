"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button, Card, MessageCard, Text } from "@opal/components";
import { Content, KeyValue, Section } from "@opal/layouts";
import { SvgBlocks } from "@opal/icons";
import type { StatusColor } from "@opal/types";
import type {
  MarketplaceEntryStatus,
  MarketplacePreview as Preview,
  MarketplacePreviewEntry,
} from "@/lib/marketplaces/types";
import { useMarketplaceCopy } from "@/lib/marketplaces/hooks";
import { sortMarketplaceEntries } from "@/lib/marketplaces/utils";
import PluginNeedList from "@/sections/plugins/PluginNeedList";

export const ENTRY_STATUS_COLOR = {
  ok: "success",
  blocked: "warning",
  not_supported: "default",
} as const satisfies Record<MarketplaceEntryStatus, StatusColor>;

interface PreviewEntryProps {
  entry: MarketplacePreviewEntry;
}

function PreviewEntry({ entry }: PreviewEntryProps) {
  const t = useTranslations("plugins.marketplaces");
  const copy = useMarketplaceCopy();
  const installs = entry.skills.length > 0 || entry.needs.length > 0;
  return (
    <Card padding={2} border="solid">
      <Section gap={2} alignItems="stretch" height="auto">
        <Content
          icon={SvgBlocks}
          title={entry.key}
          description={
            entry.description ?? copy.entryReason(entry) ?? undefined
          }
          badge={[
            {
              title: t(`status.${entry.status}`),
              color: ENTRY_STATUS_COLOR[entry.status],
            },
            ...(entry.version
              ? [{ title: t("preview.version", { version: entry.version }) }]
              : []),
          ]}
        />
        {entry.status === "ok" && installs && (
          <Section gap={1} alignItems="stretch" height="auto">
            <Text as="p" font="secondary-action" color="text-03">
              {t("preview.willInstall")}
            </Text>
            {entry.skills.length > 0 && (
              <Text as="p" font="secondary-body" color="text-03">
                {t("preview.skills", {
                  count: entry.skills.length,
                  names: entry.skills.map((skill) => skill.name).join(", "),
                })}
              </Text>
            )}
            {entry.needs.length > 0 && (
              <PluginNeedList needs={entry.needs} interactive={false} />
            )}
          </Section>
        )}
        {entry.warnings.map((warning) => (
          <Text
            key={warning}
            as="p"
            font="secondary-body"
            color="status-warning-05"
          >
            {warning}
          </Text>
        ))}
      </Section>
    </Card>
  );
}

interface MarketplacePreviewProps {
  preview: Preview;
}

export default function MarketplacePreview({
  preview,
}: MarketplacePreviewProps) {
  const t = useTranslations("plugins.marketplaces");
  const locale = useLocale();
  const copy = useMarketplaceCopy();
  const [showUnusable, setShowUnusable] = useState(false);
  const entries = sortMarketplaceEntries(preview.entries, locale);
  const ready = entries.filter((entry) => entry.status === "ok");
  const unusable = entries.filter((entry) => entry.status !== "ok");
  const limitNote = copy.limitNote(preview.entries);
  return (
    <Section gap={3} alignItems="stretch" height="auto">
      <Card padding={4} border="solid">
        <Section gap={3} alignItems="stretch" height="auto">
          <KeyValue
            label={t("source.repository")}
            value={preview.repository}
            mono
          />
          <KeyValue
            label={t("source.folder")}
            value={preview.folder ?? t("source.root")}
            mono={preview.folder !== null}
          />
          <KeyValue
            label={t("source.ref")}
            value={preview.ref ?? t("source.defaultBranch")}
            mono={preview.ref !== null}
          />
          {preview.revision && (
            <KeyValue
              label={t("source.commit")}
              value={preview.revision.slice(0, 12)}
              mono
            />
          )}
        </Section>
      </Card>
      {preview.status === "failed" ? (
        <MessageCard
          variant="error"
          outerPadding={1}
          innerPadding={1}
          title={t("preview.failedTitle")}
          description={preview.reason ?? undefined}
        />
      ) : (
        <Section gap={2} alignItems="stretch" height="auto">
          <Text as="p" font="main-ui-action" color="text-04">
            {t("preview.title", {
              name: preview.name ?? preview.repository,
              count: ready.length,
            })}
          </Text>
          {preview.entries.length > 0 && (
            <Text as="p" font="secondary-body" color="text-03">
              {t("preview.summary", {
                ready: ready.length,
                blocked: unusable.filter((entry) => entry.status === "blocked")
                  .length,
                unsupported: unusable.filter(
                  (entry) => entry.status === "not_supported"
                ).length,
              })}
            </Text>
          )}
          {limitNote && (
            <MessageCard
              variant="warning"
              outerPadding={1}
              innerPadding={1}
              title={t("reason.limitTitle")}
              description={limitNote}
            />
          )}
          {preview.entries.length === 0 ? (
            <Text as="p" font="secondary-body" color="text-03">
              {t("preview.empty")}
            </Text>
          ) : (
            <>
              {ready.map((entry) => (
                <PreviewEntry key={entry.key} entry={entry} />
              ))}
              {unusable.length > 0 && (
                <Section height="auto" alignItems="start">
                  <Button
                    prominence="tertiary"
                    size="sm"
                    onClick={() => setShowUnusable((shown) => !shown)}
                  >
                    {showUnusable
                      ? t("preview.hideUnusable")
                      : t("preview.showUnusable", { count: unusable.length })}
                  </Button>
                </Section>
              )}
              {showUnusable &&
                unusable.map((entry) => (
                  <PreviewEntry key={entry.key} entry={entry} />
                ))}
            </>
          )}
        </Section>
      )}
    </Section>
  );
}
