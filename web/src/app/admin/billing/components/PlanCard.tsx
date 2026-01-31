"use client";

import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import { Section } from "@/layouts/general-layouts";
export interface PlanFeature {
  icon: React.FunctionComponent<IconProps>;
  text: string;
}

export interface PlanButton {
  label: string;
  variant: "primary" | "secondary";
  onClick?: () => void;
  href?: string;
}

interface PlanCardProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  pricing?: string;
  description?: string;
  button: PlanButton;
  features: PlanFeature[];
  featuresPrefix?: string;
  isCurrentPlan?: boolean;
  hideFeatures?: boolean;
}

export function PlanCard({
  icon: Icon,
  title,
  pricing,
  description,
  button,
  features,
  featuresPrefix,
  isCurrentPlan,
  hideFeatures,
}: PlanCardProps) {
  return (
    <Card
      padding={0}
      gap={0}
      alignItems="stretch"
      aria-label={title + " plan card"}
      className="plan-card"
    >
      <Section
        flexDirection="column"
        alignItems="stretch"
        padding={1}
        height="auto"
        aria-label={title + " upper content of plan card"}
      >
        {/* Title */}
        <Section
          flexDirection="column"
          alignItems="start"
          gap={0.25}
          width="full"
        >
          <Icon size={24} />
          <Text headingH3 text04>
            {title}
          </Text>
        </Section>

        {/* Pricing description */}
        <Section
          flexDirection="row"
          justifyContent="start"
          alignItems="center"
          gap={0.5}
          height="auto"
        >
          {pricing && (
            <Text headingH2 text04>
              {pricing}
            </Text>
          )}
          {description && (
            <Text mainUiBody text03>
              {description}
            </Text>
          )}
        </Section>

        <div className="plan-card-button">
          {isCurrentPlan ? (
            <div className="plan-card-current-badge">
              <Text mainUiAction text03>
                Your Current Plan
              </Text>
            </div>
          ) : button.href ? (
            /* External link button  - i.e. Contact Sales button */
            <Button
              main
              secondary
              href={button.href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {button.label}
            </Button>
          ) : (
            <Button main primary onClick={button.onClick}>
              {button.label}
            </Button>
          )}
        </div>
      </Section>

      <div
        className="plan-card-features-container"
        data-hidden={hideFeatures ? "true" : "false"}
        aria-label={title + " features section of plan card"}
      >
        <Section
          flexDirection="column"
          alignItems="start"
          justifyContent="start"
          gap={1}
          padding={1}
        >
          {featuresPrefix && (
            <Text mainUiBody text03>
              {featuresPrefix}
            </Text>
          )}
          <Section
            flexDirection="column"
            alignItems="start"
            gap={0.5}
            height="auto"
          >
            {features.map((feature) => (
              <Section
                key={feature.text}
                flexDirection="row"
                alignItems="start"
                justifyContent="start"
                gap={0.25}
                width="fit"
                height="auto"
              >
                <div className="plan-card-feature-icon">
                  <feature.icon size={16} />
                </div>
                <Text mainUiBody text03>
                  {feature.text}
                </Text>
              </Section>
            ))}
          </Section>
        </Section>
      </div>
    </Card>
  );
}
