import React from "react";
import Link from "next/link";
import type { Route } from "next";
import { Button } from "@opal/components";
import { FINAL_SETUP_CONFIG } from "@/sections/onboarding/constants";
import { FinalStepItemProps } from "@/interfaces/onboarding";
import { SvgExternalLink } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";
import { Card } from "@/refresh-components/cards";
import { useTranslation } from "react-i18next";

const FinalStepItem = React.memo(
  ({
    title,
    description,
    icon: Icon,
    buttonText,
    buttonHref,
  }: FinalStepItemProps) => {
    const { t } = useTranslation();
    const isExternalLink = buttonHref.startsWith("http");
    const linkProps = isExternalLink
      ? { target: "_blank", rel: "noopener noreferrer" }
      : {};

    let displayTitle = title;
    let displayDescription = description;
    let displayButtonText = buttonText;

    if (title === "Select web search provider") {
      displayTitle = t(
        "onboarding.final.web_search_title",
        "Select web search provider"
      );
      displayDescription = t(
        "onboarding.final.web_search_desc",
        "Enable Onyx to search the internet for information."
      );
      displayButtonText = t("onboarding.final.web_search_btn", "Web Search");
    } else if (title === "Enable image generation") {
      displayTitle = t(
        "onboarding.final.image_gen_title",
        "Enable image generation"
      );
      displayDescription = t(
        "onboarding.final.image_gen_desc",
        "Set up models to create images in your chats."
      );
      displayButtonText = t(
        "onboarding.final.image_gen_btn",
        "Image Generation"
      );
    } else if (title === "Invite your team") {
      displayTitle = t(
        "onboarding.final.invite_team_title",
        "Invite your team"
      );
      displayDescription = t(
        "onboarding.final.invite_team_desc",
        "Manage users and permissions for your team"
      );
      displayButtonText = t("onboarding.final.invite_team_btn", "Manage Users");
    }

    return (
      <Card padding={0.25} variant="secondary">
        <ContentAction
          icon={Icon}
          title={displayTitle}
          description={displayDescription}
          sizePreset="main-ui"
          variant="section"
          padding="sm"
          rightChildren={
            <Link href={buttonHref as Route} {...linkProps}>
              <Button prominence="tertiary" rightIcon={SvgExternalLink}>
                {displayButtonText}
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
  return (
    <Section gap={0.5}>
      {FINAL_SETUP_CONFIG.map((item) => (
        <FinalStepItem key={item.title} {...item} />
      ))}
    </Section>
  );
}
