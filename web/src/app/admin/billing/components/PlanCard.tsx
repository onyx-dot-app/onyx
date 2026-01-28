"use client";

import { Card } from "@/components/ui/card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import type { IconProps } from "@opal/types";
import { Section } from "@/layouts/general-layouts";

// -----------------------------------------------------------------------------
// Types
// -----------------------------------------------------------------------------

export interface PlanFeature {
  icon: React.FunctionComponent<IconProps>;
  text: string;
}

export interface PlanPricing {
  amount: string;
  details: string[];
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
  pricing?: PlanPricing;
  description?: string;
  button: PlanButton;
  features: PlanFeature[];
  featuresPrefix?: string;
  isCurrentPlan?: boolean;
  hideFeatures?: boolean;
}

// -----------------------------------------------------------------------------
// PlanCard Component
// -----------------------------------------------------------------------------

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
    <Card className="plan-card">
      <div className="plan-card-content">
        <div className="plan-card-info">
          {/* Plan title */}
          <Section flexDirection="column" alignItems="start" gap={0.25}>
            <Icon size={24} />
            <Text headingH3 text04>
              {title}
            </Text>
          </Section>

          {/* Plan pricing details */}
          {pricing && (
            <Section flexDirection="row" gap={0.5}>
              <Text headingH2 text04>
                {pricing.amount}
              </Text>
              <Section flexDirection="column" alignItems="start" gap={0.25}>
                {pricing.details.map((detail, index) => (
                  <Text key={index} secondaryBody text03>
                    {detail}
                  </Text>
                ))}
              </Section>
            </Section>
          )}

          {description && (
            <div className="plan-card-description">
              <Text secondaryBody text03>
                {description}
              </Text>
            </div>
          )}
        </div>

        <div className="plan-card-button">
          {isCurrentPlan ? (
            <div className="plan-card-current-badge">
              <Text mainUiAction text03>
                Your Current Plan
              </Text>
            </div>
          ) : button.href ? (
            <Button
              main
              secondary={button.variant === "secondary"}
              primary={button.variant === "primary"}
              href={button.href}
              target="_blank"
              rel="noopener noreferrer"
              className="w-full"
            >
              {button.label}
            </Button>
          ) : (
            <Button
              main
              secondary={button.variant === "secondary"}
              primary={button.variant === "primary"}
              onClick={button.onClick}
              className="w-full"
            >
              {button.label}
            </Button>
          )}
        </div>
      </div>

      <div
        className="plan-card-features-container"
        data-hidden={hideFeatures ? "true" : "false"}
      >
        <div className="plan-card-features">
          {featuresPrefix && (
            <Text mainUiBody text03>
              {featuresPrefix}
            </Text>
          )}
          <div className="plan-card-feature-list">
            {features.map((feature) => (
              <div key={feature.text} className="plan-card-feature-item">
                <div className="plan-card-feature-icon">
                  <feature.icon size={16} />
                </div>
                <Text mainUiBody text03>
                  {feature.text}
                </Text>
              </div>
            ))}
          </div>
        </div>
      </div>
    </Card>
  );
}
