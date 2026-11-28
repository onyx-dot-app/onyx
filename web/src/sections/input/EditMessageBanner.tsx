"use client";

import { useTranslations } from "next-intl";
import { Button, Text } from "@opal/components";
import { SvgEdit } from "@opal/icons";
import { Section } from "@opal/layouts";

interface EditMessageBannerProps {
  onCancel: () => void;
}

export function EditMessageBanner({ onCancel }: EditMessageBannerProps) {
  const t = useTranslations("chat.input.editMessageBanner");
  return (
    <Section
      flexDirection="row"
      justifyContent="between"
      height="fit"
      gap={2}
      padding={1}
      className="mb-1.5 rounded-12 border border-action-selection-05 bg-background-neutral-02"
      data-testid="edit-message-banner"
    >
      <Section
        flexDirection="row"
        justifyContent="start"
        width="auto"
        height="fit"
        gap={2}
        className="ms-1.5"
      >
        <SvgEdit className="h-4 w-4 shrink-0 stroke-action-selection-05" />
        <Text font="secondary-body" color="text-04">
          {t("label")}
        </Text>
      </Section>
      <Button
        size="xs"
        prominence="tertiary"
        aria-label={t("cancelButton.ariaLabel")}
        onClick={onCancel}
      >
        {t("cancelButton.label")}
      </Button>
    </Section>
  );
}
