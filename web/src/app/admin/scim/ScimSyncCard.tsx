import { useTranslations } from "next-intl";
import { SvgCheckCircle, SvgClock, SvgKey, SvgRefreshCw } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import { Button } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import Separator from "@/refresh-components/Separator";
import { timeAgo } from "@/lib/time";

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
    <Card gap={0.75}>
      <ContentAction
        title={t("syncTitle")}
        description={t("syncDescription")}
        sizePreset="main-ui"
        variant="section"
        paddingVariant="fit"
        rightChildren={
          hasToken ? (
            <Button
              variant="danger"
              prominence="secondary"
              onClick={onRegenerate}
              icon={SvgRefreshCw}
            >
              {t("regenerateToken")}
            </Button>
          ) : (
            <Button
              disabled={isSubmitting}
              rightIcon={SvgKey}
              onClick={onGenerate}
            >
              {t("generateToken")}
            </Button>
          )
        }
      />

      {hasToken && (
        <>
          <Separator noPadding />

          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="end"
            gap={1}
          >
            <Section alignItems="start" gap={0} width="fit">
              {isConnected ? (
                <SvgCheckCircle size={15} className="text-status-success-05" />
              ) : (
                <SvgClock size={15} className="text-theme-amber-05" />
              )}
              <Text as="p" mainUiBody text04>
                {isConnected ? t("connected") : t("waitingForConnection")}
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
                  {t("provideKeyHint")}
                </Text>
              )}
            </Section>
          </Section>
        </>
      )}
    </Card>
  );
}
