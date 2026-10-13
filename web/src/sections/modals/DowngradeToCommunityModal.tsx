"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button, MessageCard, Text } from "@opal/components";
import { SvgArrowDownCircle } from "@opal/icons";
import { ConfirmationModalLayout, toast } from "@opal/layouts";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import { downgradeToCommunity } from "@/lib/billing";

const CHANGE_KEYS = [
  "modal.madePublic.text",
  "modal.deleted.text",
  "modal.disabled.text",
  "modal.reset.text",
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
      icon={SvgArrowDownCircle}
      color="warning"
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
      <Section gap={1} alignItems="start" height="auto">
        <Section gap={0.5} alignItems="start" height="auto">
          <Text as="p" font="main-ui-body" color="text-03">
            {markdown(t("modal.intro.text"))}
          </Text>
          <Text as="p" font="main-ui-body" color="text-03">
            {t("modal.changes.text")}
          </Text>
          <ul className="list-disc space-y-0.5 ps-5">
            {CHANGE_KEYS.map((key) => (
              <Text key={key} as="li" font="main-ui-body" color="text-03">
                {markdown(t(key))}
              </Text>
            ))}
          </ul>
        </Section>
        <MessageCard
          variant="warning"
          outerPadding={1}
          innerPadding={1}
          titleMaxLines={undefined}
          title={markdown(t("modal.warning.text"))}
        />
      </Section>
    </ConfirmationModalLayout>
  );
}
