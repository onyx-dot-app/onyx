"use client";

import { useTranslations } from "next-intl";
import { Button, Card, Code, CopyButton, Tag, Text } from "@opal/components";
import { Section } from "@opal/layouts";
import { SvgExternalLink } from "@opal/icons";
import { markdown } from "@opal/utils";
import type { IntegrationPreset } from "@/lib/integrations/types";

interface PresetSetupPanelProps {
  preset: IntegrationPreset;
}

/** How to create the OAuth app of a preset at its vendor: the steps, the
 * callback URL to register, the scopes and a link to the vendor page. */
export default function PresetSetupPanel({ preset }: PresetSetupPanelProps) {
  const t = useTranslations("admin.integrations.add.setup");
  const callbackUrl = preset.callback_url;
  return (
    <Card padding={4} color="background-tint-01">
      <Section gap={4} alignItems="stretch" height="auto">
        <Text as="h3" font="main-content-emphasis" color="text-05">
          {t("title", { name: preset.name })}
        </Text>
        {preset.setup_steps.length > 0 && (
          <ol className="list-decimal ps-5 space-y-1 font-secondary-body marker:text-text-03">
            {preset.setup_steps.map((step) => (
              <li key={step}>
                <Text font="secondary-body" color="text-04">
                  {step}
                </Text>
              </li>
            ))}
          </ol>
        )}
        {callbackUrl && (
          <Section gap={1} alignItems="stretch" height="auto">
            <Text as="p" font="secondary-body" color="text-03">
              {t("callbackUrl")}
            </Text>
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="center"
              gap={1}
              height="auto"
            >
              <Section alignItems="stretch" height="auto" grow={1}>
                <Code showCopyButton={false} aria-label={t("callbackUrl")}>
                  {callbackUrl}
                </Code>
              </Section>
              <CopyButton
                size="sm"
                aria-label={t("copyCallbackUrl")}
                getCopyText={() => callbackUrl}
              />
            </Section>
          </Section>
        )}
        {preset.scopes.length > 0 && (
          <Section gap={1} alignItems="stretch" height="auto">
            <Text as="p" font="secondary-body" color="text-03">
              {t("scopes")}
            </Text>
            <Section
              flexDirection="row"
              justifyContent="start"
              gap={1}
              wrap
              height="auto"
            >
              {preset.scopes.map((scope) => (
                <Tag key={scope} title={markdown(`\`${scope}\``)} />
              ))}
            </Section>
          </Section>
        )}
        {preset.setup_url && (
          <Section alignItems="start" height="auto">
            <Button
              size="sm"
              prominence="secondary"
              rightIcon={SvgExternalLink}
              href={preset.setup_url}
              target="_blank"
            >
              {t("open", { name: preset.name })}
            </Button>
          </Section>
        )}
      </Section>
    </Card>
  );
}
