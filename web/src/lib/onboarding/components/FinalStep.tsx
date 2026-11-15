"use client";

import { useNavigation } from "@opal/navigation";
import { memo } from "react";
import type { Route } from "next";
import { useTranslations } from "next-intl";
import { Button, SelectCard } from "@opal/components";
import { SvgExternalLink } from "@opal/icons";
import { ContentAction, Section } from "@opal/layouts";
import type { IconFunctionComponent, RichStr } from "@opal/types";
import { FINAL_SETUP_CONFIG } from "@/lib/onboarding/constants";
import { useSettings } from "@/lib/settings/hooks";

interface FinalStepItemProps {
  icon: IconFunctionComponent;
  title: string | RichStr;
  description: string | RichStr;
  buttonText: string | RichStr;
  buttonHref: Route;
}

/** One optional setup: the card and its button both open the page. */
function FinalStepItemInner({
  icon,
  title,
  description,
  buttonText,
  buttonHref,
}: FinalStepItemProps) {
  const navigation = useNavigation();
  const link = navigation.linkTo(buttonHref);

  return (
    <SelectCard
      state="empty"
      padding={1}
      rounding={4}
      onClick={() => navigation.go(buttonHref)}
    >
      <ContentAction
        font="main-ui-action"
        icon={icon}
        title={title}
        description={description}
        padding={2}
        rightChildren={
          <Button
            prominence="tertiary"
            rightIcon={SvgExternalLink}
            href={link.href}
            // The link navigates itself; the card must not navigate again.
            onClick={(event) => {
              event.stopPropagation();
              link.onClick(event);
            }}
          >
            {buttonText}
          </Button>
        }
      />
    </SelectCard>
  );
}

const FinalStepItem = memo(FinalStepItemInner);

export default function FinalStep() {
  const t = useTranslations("onboarding");
  const { appName } = useSettings();

  return (
    <Section gap={2}>
      {FINAL_SETUP_CONFIG.map((item) => (
        <FinalStepItem
          key={item.titleKey}
          icon={item.icon}
          buttonHref={item.buttonHref}
          title={t(item.titleKey)}
          description={t(item.descriptionKey, { appName })}
          buttonText={t(item.buttonTextKey)}
        />
      ))}
    </Section>
  );
}
