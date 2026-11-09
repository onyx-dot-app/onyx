"use client";

import { useTranslations } from "next-intl";
import { Badge, Card, CopyButton, MessageCard, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import type { MarketplacePreview as Preview } from "@/lib/marketplaces/types";

const sampleCatalog = JSON.stringify(
  {
    name: "team-skills",
    plugins: [{ name: "team-skills", source: "./team-skills" }],
  },
  null,
  2
);

interface MarketplacePreviewProps {
  preview: Preview;
}

export default function MarketplacePreview({
  preview,
}: MarketplacePreviewProps) {
  const t = useTranslations("marketplaces");
  if (preview.status === "failed") {
    return (
      <Section height="auto" alignItems="stretch" gap={2}>
        <MessageCard
          variant="error"
          outerPadding={1}
          innerPadding={1}
          title={t("previewFailed")}
          description={preview.reason}
        />
        {preview.reason.includes("Marketplace manifest is missing") && (
          <Card padding={2}>
            <Section height="auto" alignItems="stretch" gap={2}>
              <Text font="main-ui-action">{t("sampleTitle")}</Text>
              <Text font="secondary-body">{t("sampleDescription")}</Text>
              <pre className="overflow-x-auto">
                <Text font="secondary-mono">{sampleCatalog}</Text>
              </pre>
              <CopyButton getCopyText={() => sampleCatalog}>
                {t("copySample")}
              </CopyButton>
            </Section>
          </Card>
        )}
      </Section>
    );
  }
  return (
    <Section height="auto" alignItems="stretch" gap={2}>
      <Text font="secondary-mono" wordWrap="wrap-anywhere">
        {preview.revision}
      </Text>
      {preview.entries.length === 0 && (
        <Text font="secondary-body">{t("emptyPreview")}</Text>
      )}
      {preview.entries.map((entry) => (
        <Card key={entry.entry_key} padding={2} border="solid">
          <Section height="auto" alignItems="stretch" gap={1}>
            <Section
              height="auto"
              flexDirection="row"
              justifyContent="between"
              gap={2}
            >
              <Text font="main-ui-action" wordWrap="wrap-anywhere">
                {entry.status === "ok" ? entry.name : entry.entry_key}
              </Text>
              <Badge
                color={entry.status === "ok" ? "success" : "warning"}
                title={t(entry.status)}
              />
            </Section>
            {"path" in entry && (
              <Text font="secondary-mono" wordWrap="wrap-anywhere">
                {entry.path}
              </Text>
            )}
            <Text font="secondary-body" wordWrap="wrap-anywhere">
              {entry.status === "ok" ? entry.description : entry.reason}
            </Text>
          </Section>
        </Card>
      ))}
    </Section>
  );
}
