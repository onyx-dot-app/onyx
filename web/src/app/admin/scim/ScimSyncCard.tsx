import { SvgCheckCircle, SvgClock, SvgKey, SvgRefreshCw } from "@opal/icons";
import { ContentAction } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import { Button, Divider } from "@opal/components";
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
  return (
    <Card gap={0.75}>
      <ContentAction
        title="SCIM 同步"
        description="连接你的身份提供商，以导入并同步用户和用户组。"
        sizePreset="main-ui"
        variant="section"
        padding="fit"
        rightChildren={
          hasToken ? (
            <Button
              variant="danger"
              prominence="secondary"
              onClick={onRegenerate}
              icon={SvgRefreshCw}
            >
              重新生成 Token
            </Button>
          ) : (
            <Button
              disabled={isSubmitting}
              rightIcon={SvgKey}
              onClick={onGenerate}
            >
              生成 SCIM Token
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
                {isConnected ? "已连接" : "等待连接"}
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
                  将 SCIM Key 提供给你的身份提供商，即可开始同步用户和用户组。
                </Text>
              )}
            </Section>
          </Section>
        </>
      )}
    </Card>
  );
}
