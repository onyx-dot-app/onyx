import React from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type { Route } from "next";
import { Button } from "@opal/components";
import { FINAL_SETUP_CONFIG } from "@/sections/onboarding/constants";
import { FinalStepItemProps } from "@/interfaces/onboarding";
import { SvgExternalLink } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";
import { Card } from "@/refresh-components/cards";

const FINAL_SETUP_I18N_KEYS = [
  {
    titleKey: "onboarding.selectWebSearchProvider",
    descriptionKey: "onboarding.enableWebSearchDescription",
    buttonKey: "onboarding.webSearchButton",
  },
  {
    titleKey: "onboarding.enableImageGeneration",
    descriptionKey: "onboarding.imageGenerationDescription",
    buttonKey: "onboarding.imageGenerationButton",
  },
  {
    titleKey: "onboarding.inviteYourTeam",
    descriptionKey: "onboarding.inviteTeamDescription",
    buttonKey: "onboarding.manageUsersButton",
  },
] as const;

const FinalStepItem = React.memo(
  ({
    title,
    description,
    icon: Icon,
    buttonText,
    buttonHref,
  }: FinalStepItemProps) => {
    const isExternalLink = buttonHref.startsWith("http");
    const linkProps = isExternalLink
      ? { target: "_blank", rel: "noopener noreferrer" }
      : {};

    return (
      <Card padding={0.25} variant="secondary">
        <ContentAction
          icon={Icon}
          title={title}
          description={description}
          sizePreset="main-ui"
          variant="section"
          paddingVariant="sm"
          rightChildren={
            <Link href={buttonHref as Route} {...linkProps}>
              <Button prominence="tertiary" rightIcon={SvgExternalLink}>
                {buttonText}
              </Button>
            </Link>
          }
        />
      </Card>
    );
  }
);
FinalStepItem.displayName = "FinalStepItem";

export default function FinalStep() {
  const t = useTranslations("chat");

  return (
    <Section gap={0.5}>
      {FINAL_SETUP_CONFIG.map((item, index) => {
        const i18nKeys = FINAL_SETUP_I18N_KEYS[index];
        if (!i18nKeys) return null;
        return (
          <FinalStepItem
            key={item.buttonHref}
            icon={item.icon}
            buttonHref={item.buttonHref}
            title={t(i18nKeys.titleKey)}
            description={t(i18nKeys.descriptionKey)}
            buttonText={t(i18nKeys.buttonKey)}
          />
        );
      })}
    </Section>
  );
}
