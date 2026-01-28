"use client";

import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgCheck } from "@opal/icons";
import { IconProps } from "@opal/types";

interface PlanCardProps {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  description?: string;
  price?: {
    main: string;
    sub?: string;
  };
  features: string[];
  featuresPrefix?: string;
  ctaLabel: string;
  ctaHref?: string;
  onCtaClick?: () => void;
  isCurrentPlan?: boolean;
  isExternal?: boolean;
}

export default function PlanCard({
  icon: Icon,
  title,
  description,
  price,
  features,
  featuresPrefix,
  ctaLabel,
  ctaHref,
  onCtaClick,
  isCurrentPlan,
  isExternal,
}: PlanCardProps) {
  return (
    <Card className="flex-1">
      <Section gap={1} alignItems="start" height="auto">
        {/* Header with icon and title */}
        <Section
          flexDirection="row"
          gap={0.5}
          justifyContent="start"
          height="auto"
        >
          <Icon className="w-5 h-5 stroke-text-04" />
          <Text headingH3>{title}</Text>
        </Section>

        {/* Description or price */}
        {description && (
          <Text secondaryBody text03>
            {description}
          </Text>
        )}

        {price && (
          <Section gap={0.25} alignItems="start" height="auto">
            <div className="billing-price-main">
              <Text mainContentEmphasis>{price.main}</Text>
            </div>
            {price.sub && (
              <Text secondaryBody text03>
                {price.sub}
              </Text>
            )}
          </Section>
        )}

        {/* CTA Button or Current Plan Badge */}
        {isCurrentPlan ? (
          <div className="billing-current-plan-badge">
            <Text secondaryBody text03>
              Your Current Plan
            </Text>
          </div>
        ) : (
          <Button
            main
            primary={!isExternal}
            secondary={isExternal}
            onClick={onCtaClick}
            href={ctaHref}
            target={isExternal ? "_blank" : undefined}
          >
            {ctaLabel}
          </Button>
        )}
      </Section>

      {/* Features section with light background */}
      <div className="bg-background-tint-01 rounded-12 -mx-4 -mb-4 mt-2">
        <Section gap={1} padding={1} alignItems="start" height="auto">
          {featuresPrefix && (
            <Text secondaryBody text03>
              {featuresPrefix}
            </Text>
          )}

          <Section gap={0.5} alignItems="start" height="auto">
            {features.map((feature, index) => (
              <Section
                key={index}
                flexDirection="row"
                gap={0.25}
                justifyContent="start"
                alignItems="center"
                height="auto"
              >
                <div className="billing-feature-icon">
                  <SvgCheck className="w-4 h-4 stroke-status-success-05" />
                </div>
                <Text secondaryBody>{feature}</Text>
              </Section>
            ))}
          </Section>
        </Section>
      </div>
    </Card>
  );
}
