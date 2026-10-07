"use client";

import { useTranslations } from "next-intl";
import { Button, Card } from "@opal/components";
import { ContentAction } from "@opal/layouts";
import { SvgPlay } from "@opal/icons";
import { useSettings } from "@/lib/settings/hooks";

interface ConnectorsCheckPromptCardProps {
  /** Disabled until the credential section is valid. */
  disabled: boolean;
  onStart: () => void;
}

/**
 * Where the checks card will be, before the user asks for the checks. They
 * run only on request, so a page visit costs no credential calls.
 */
export function ConnectorsCheckPromptCard({
  disabled,
  onStart,
}: ConnectorsCheckPromptCardProps) {
  const t = useTranslations("admin.connectorChecks.prompt");
  const { appName } = useSettings();

  return (
    <Card border="solid" rounding={4} padding={2}>
      <ContentAction
        title={t("title")}
        description={t("description", { appName })}
        sizePreset="main-content"
        variant="section"
        center
        rightChildren={
          <Button icon={SvgPlay} disabled={disabled} onClick={onStart}>
            {t("startButton.label")}
          </Button>
        }
      />
    </Card>
  );
}
