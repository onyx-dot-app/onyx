"use client";

import { memo } from "react";
import { useTranslations } from "next-intl";
import { Button, IconContainer, SelectCard } from "@opal/components";
import { SvgCheckCircle, SvgSettings } from "@opal/icons";
import { ContentAction, Section } from "@opal/layouts";
import type { IconFunctionComponent } from "@opal/types";
import { cn } from "@opal/utils";
import { noProp } from "@/lib/utils";

export interface LLMProviderCardProps {
  icon: IconFunctionComponent;
  title: string;
  description: string;
  /** The top-right button's label, e.g. "Connect". */
  actionLabel: string;
  /** The top-right button's icon, after the label. */
  actionIcon: IconFunctionComponent;
  /** A connected card shows a check in place of the button. */
  isConnected?: boolean;
  /** Runs on a click on the card or on its button (Connect or settings). */
  onClick: () => void;
}

/**
 * A provider to set up, laid out like the new-provider cards on the Language
 * Models admin page: icon, name and company, and a tertiary action top right.
 */
function LLMProviderCardInner({
  icon,
  title,
  description,
  actionLabel,
  actionIcon,
  isConnected,
  onClick,
}: LLMProviderCardProps) {
  const t = useTranslations("onboarding");
  return (
    <SelectCard
      state={isConnected ? "filled" : "empty"}
      padding={1}
      // 12px: concentric inside the step card's 16px corners and 4px inset.
      rounding={3}
      onClick={onClick}
    >
      <ContentAction
        icon={icon}
        title={title}
        description={description}
        titleMaxLines={1}
        descriptionMaxLines={1}
        sizePreset="main-ui"
        variant="section"
        padding={1}
        rightChildren={
          isConnected ? (
            // 28px tall: the md button, and the check boxed to match it.
            <Section
              flexDirection="row"
              justifyContent="start"
              alignItems="start"
              gap={0}
              width="fit"
              height="auto"
            >
              <Button
                prominence="tertiary"
                size="md"
                icon={SvgSettings}
                tooltip={t("llmStep.providerCard.settingsButton.ariaLabel")}
                aria-label={t("llmStep.providerCard.settingsButton.ariaLabel")}
                onClick={noProp(onClick)}
              />
              <Section padding={1} width="fit" height="auto">
                <IconContainer
                  icon={({ className, ...props }) => (
                    <SvgCheckCircle
                      className={cn(className, "stroke-status-success-05")}
                      {...props}
                    />
                  )}
                />
              </Section>
            </Section>
          ) : (
            <Button
              rightIcon={actionIcon}
              prominence="tertiary"
              size="md"
              onClick={noProp(onClick)}
            >
              {actionLabel}
            </Button>
          )
        }
      />
    </SelectCard>
  );
}

const LLMProviderCard = memo(LLMProviderCardInner);
export default LLMProviderCard;
