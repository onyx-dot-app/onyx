"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgAlertTriangle } from "@opal/icons";
import { ConfirmationModalLayout, toast } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { downgradeToCommunity } from "@/lib/billing";

const CONSEQUENCE_KEYS = [
  "modal.connectors.text",
  "modal.groups.text",
  "modal.features.text",
  "modal.license.text",
] as const;

interface DowngradeToCommunityModalProps {
  onClose: () => void;
}

// Consent screen: spells out what becomes public and what is removed before
// a self-hosted admin drops the deployment to the Community tier.
export default function DowngradeToCommunityModal({
  onClose,
}: DowngradeToCommunityModalProps) {
  const t = useTranslations("admin.billing.downgrade");
  const [isDowngrading, setIsDowngrading] = useState(false);

  async function handleDowngrade() {
    setIsDowngrading(true);
    try {
      await downgradeToCommunity();
      // Tier, gating and branding are cached all over the app, so start clean.
      window.location.reload();
    } catch (error) {
      toast.error(t("failed.text"), {
        description: error instanceof Error ? error.message : undefined,
      });
      setIsDowngrading(false);
    }
  }

  return (
    <ConfirmationModalLayout
      icon={SvgAlertTriangle}
      title={t("modal.title")}
      description={t("modal.description")}
      // Closing would not stop the request, and reopening could send it twice.
      onClose={isDowngrading ? undefined : onClose}
      submit={
        <Button
          variant="danger"
          disabled={isDowngrading}
          onClick={handleDowngrade}
        >
          {isDowngrading
            ? t("modal.confirmButton.loading")
            : t("modal.confirmButton.label")}
        </Button>
      }
    >
      <Section gap={0.75} alignItems="start" height="auto">
        {CONSEQUENCE_KEYS.map((key) => (
          <Text key={key} as="p" font="main-ui-muted" color="text-03">
            {t(key)}
          </Text>
        ))}
      </Section>
    </ConfirmationModalLayout>
  );
}
