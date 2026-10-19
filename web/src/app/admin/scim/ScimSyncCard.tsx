import { useLocale, useTranslations } from "next-intl";
import { SvgCheckCircle, SvgClock, SvgKey, SvgRefreshCw } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { Button, Card, Divider, Text } from "@opal/components";
import { timeAgo } from "@opal/time";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface ScimSyncCardProps {
  hasToken: boolean;
  isConnected: boolean;
  lastUsedAt: string | null;
  idpDomain: string | null;
  isSubmitting: boolean;
  onGenerate: () => void;
  onRegenerate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function ScimSyncCard({
  hasToken,
  isConnected,
  lastUsedAt,
  idpDomain,
  isSubmitting,
  onGenerate,
  onRegenerate,
}: ScimSyncCardProps) {
  const t = useTranslations("admin.scim");
  const locale = useLocale();

  return (
    <Card border="solid" rounding={4}>
      <Section alignItems="start" height="fit" gap={3}>
        <ContentAction
          title={t("card.title")}
          description={t("card.description")}
          sizePreset="main-ui"
          variant="section"
          padding={0}
          rightChildren={
            hasToken ? (
              <Button
                variant="danger"
                prominence="secondary"
                onClick={onRegenerate}
                icon={SvgRefreshCw}
              >
                {t("card.regenerate.label")}
              </Button>
            ) : (
              <Button
                disabled={isSubmitting}
                rightIcon={SvgKey}
                onClick={onGenerate}
              >
                {t("card.generate.label")}
              </Button>
            )
          }
        />

        {hasToken && (
          <>
            <Divider paddingParallel={0} paddingPerpendicular={0} />

            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="end"
              gap={4}
            >
              <Section alignItems="start" gap={0} width="fit">
                {isConnected ? (
                  <SvgCheckCircle
                    size={15}
                    className="text-status-success-05"
                  />
                ) : (
                  <SvgClock size={15} className="text-theme-amber-05" />
                )}
                <Text font="main-ui-body" color="text-04" as="p">
                  {isConnected
                    ? t("card.connected.label")
                    : t("card.waiting.label")}
                </Text>
              </Section>

              <Section alignItems="end" gap={0} width="fit">
                {isConnected ? (
                  <>
                    {idpDomain && (
                      <Text font="secondary-action" color="text-03" as="p">
                        {idpDomain}
                      </Text>
                    )}
                    <Text font="secondary-body" color="text-03" as="p">
                      {timeAgo(lastUsedAt, locale) ?? ""}
                    </Text>
                  </>
                ) : (
                  <div className="max-w-[240px]">
                    <Text
                      as="p"
                      font="secondary-body"
                      color="text-03"
                      textPosition="text-end"
                    >
                      {t("card.waiting.description")}
                    </Text>
                  </div>
                )}
              </Section>
            </Section>
          </>
        )}
      </Section>
    </Card>
  );
}
