import React from "react";
import Link from "next/link";
import type { Route } from "next";
import Button from "@/refresh-components/buttons/Button";
import { FINAL_SETUP_CONFIG } from "@/refresh-components/onboarding/constants";
import { FinalStepItemProps } from "@/refresh-components/onboarding/types";
import { SvgExternalLink } from "@opal/icons";
import { LineItemLayout, Section } from "@/layouts/general-layouts";
import { Card } from "@/refresh-components/cards";

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
        <LineItemLayout
          icon={Icon}
          title={title}
          description={description}
          rightChildren={
            <Link href={buttonHref as Route} {...linkProps}>
              <Button tertiary rightIcon={SvgExternalLink}>
                {buttonText}
              </Button>
            </Link>
          }
          rightChildrenReducedPadding
          variant="tertiary"
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
