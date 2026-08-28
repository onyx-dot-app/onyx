import { useTranslations } from "next-intl";
import { SvgCheckCircle, SvgClock, SvgKey, SvgRefreshCw } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { Button, Card, Divider } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
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
                <Text as="p" mainUiBody text04>
                  {isConnected
                    ? t("card.connected.label")
                    : t("card.waiting.label")}
                </Text>
              </Section>

              <Section alignItems="end" gap={0} width="fit">
                {isConnected ? (
                  <>
                    {idpDomain && (
                      <Text as="p" secondaryAction text03>
                        {idpDomain}
                      </Text>
                    )}
                    <Text as="p" secondaryBody text03>
                      {timeAgo(lastUsedAt)}
                    </Text>
                  </>
                ) : (
                  <Text
                    as="p"
                    secondaryBody
                    text03
                    className="max-w-[240px] text-right"
                  >
                    {t("card.waiting.description")}
                  </Text>
                )}
              </Section>
            </Section>
          </>
        )}
      </Section>
    </Card>
  );
}
