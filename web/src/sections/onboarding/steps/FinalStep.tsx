import React from "react";
import Link from "next/link";
import type { Route } from "next";
import { Button, Card } from "@opal/components";
import { FINAL_SETUP_CONFIG } from "@/sections/onboarding/constants";
import { FinalStepItemProps } from "@/interfaces/onboarding";
import { SvgExternalLink } from "@opal/icons";
import { Section } from "@/layouts/general-layouts";
import { ContentAction } from "@opal/layouts";

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
      <Card background="none" border="solid" padding={1} rounding="lg">
        <Section alignItems="start" height="fit">
          <ContentAction
            icon={Icon}
            title={title}
            description={description}
            sizePreset="main-ui"
            variant="section"
            padding={1}
            rightChildren={
              <Link href={buttonHref as Route} {...linkProps}>
                <Button prominence="tertiary" rightIcon={SvgExternalLink}>
                  {buttonText}
                </Button>
              </Link>
            }
          />
        </Section>
      </Card>
    );
  }
);
FinalStepItem.displayName = "FinalStepItem";

export default function FinalStep() {
  return (
    <Section gap={2}>
      {FINAL_SETUP_CONFIG.map((item) => (
        <FinalStepItem key={item.title} {...item} />
      ))}
    </Section>
  );
}
