"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Card,
  CopyButton,
  Divider,
  LinkButton,
} from "@opal/components";
import { ContentAction, Section, toast } from "@opal/layouts";
import { SvgDownload } from "@opal/icons";
import { DOCS_BASE_URL } from "@/lib/constants";
import { downloadOnyxPlugin } from "@/lib/integrations/svc";
import { useSettings } from "@/lib/settings/hooks";

const GUIDES_URL = `${DOCS_BASE_URL}/overview/onyx_anywhere/mcp_server#connect-your-ai-tools`;

export default function ConnectAiTools() {
  const t = useTranslations("mcpOAuth.connectTools");
  const settings = useSettings();
  const mcpUrl = settings.onyx_mcp_url;
  const [downloading, setDownloading] = useState(false);

  async function download() {
    setDownloading(true);
    try {
      await downloadOnyxPlugin();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("downloadFailed"));
    } finally {
      setDownloading(false);
    }
  }

  // Set only when MCP clients can sign in through the Onyx OAuth provider.
  if (!mcpUrl) return null;

  return (
    <Section gap={3} height="fit" alignItems="stretch">
      <ContentAction
        font="main-content-emphasis"
        title={t("title")}
        description={t("description")}
        center
        padding={0}
        rightChildren={
          <LinkButton href={GUIDES_URL} target="_blank">
            {t("guides")}
          </LinkButton>
        }
      />
      <Card border="solid" rounding={4}>
        <Section height="fit" alignItems="stretch" gap={3}>
          <ContentAction
            font="main-ui-action"
            title={t("mcpUrl.title")}
            description={mcpUrl}
            center
            padding={0}
            rightChildren={
              <CopyButton prominence="secondary" getCopyText={() => mcpUrl}>
                {t("mcpUrl.copy")}
              </CopyButton>
            }
          />
          {settings.onyx_plugin_export_enabled && (
            <>
              <Divider />
              <ContentAction
                font="main-ui-action"
                title={t("plugin.title")}
                description={t("plugin.description")}
                center
                padding={0}
                rightChildren={
                  <Button
                    prominence="secondary"
                    icon={SvgDownload}
                    disabled={downloading}
                    onClick={() => void download()}
                  >
                    {t("plugin.download")}
                  </Button>
                }
              />
            </>
          )}
        </Section>
      </Card>
    </Section>
  );
}
