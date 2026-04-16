import { SvgCheckCircle, SvgClock, SvgKey, SvgRefreshCw } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import { Button, Divider } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
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
  return (
    <Card gap={0.75}>
      <ContentAction
        title="SCIM Sync"
        description="Connect your identity provider to import and sync users and groups."
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
              Regenerate Token
            </Button>
          ) : (
            <Button
              disabled={isSubmitting}
              rightIcon={SvgKey}
              onClick={onGenerate}
            >
              Generate SCIM Token
            </Button>
          )
        }
      />

      {hasToken && (
        <>
          <Divider paddingParallel="fit" paddingPerpendicular="fit" />

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
                {isConnected ? "Connected" : "Waiting for Connection"}
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
                  Provide the SCIM key to your identity provider to begin
                  syncing users and groups.
                </Text>
              )}
            </Section>
          </Section>
        </>
      )}
    </Card>
  );
}
