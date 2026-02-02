"use client";

import {
  SvgArrowUpCircle,
  SvgBarChart,
  SvgFileText,
  SvgGlobe,
  SvgHeadsetMic,
  SvgKey,
  SvgLock,
  SvgOrganization,
  SvgPaintBrush,
  SvgSearch,
  SvgServer,
  SvgUsers,
} from "@opal/icons";
import "./billing.css";
import type { IconProps } from "@opal/types";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { Section } from "@/layouts/general-layouts";

const SALES_URL = "https://www.onyx.app/contact-sales";

// ----------------------------------------------------------------------------
// Types
// ----------------------------------------------------------------------------

interface PlanFeature {
  icon: React.FunctionComponent<IconProps>;
  text: string;
}

interface PlanConfig {
  icon: React.FunctionComponent<IconProps>;
  title: string;
  pricing?: string;
  description: string;
  buttonLabel: string;
  buttonVariant: "primary" | "secondary";
  buttonIcon?: React.FunctionComponent<IconProps>;
  onClick?: () => void;
  href?: string;
  features: PlanFeature[];
  featuresPrefix: string;
  isCurrentPlan?: boolean;
}

// ----------------------------------------------------------------------------
// Plan Features
// ----------------------------------------------------------------------------

const BUSINESS_FEATURES: PlanFeature[] = [
  { icon: SvgSearch, text: "Enterprise Search" },
  { icon: SvgBarChart, text: "Query History & Usage Dashboard" },
  { icon: SvgServer, text: "On-Premise Deployments" },
  { icon: SvgGlobe, text: "Region-Specific Deployments" },
  { icon: SvgUsers, text: "RBAC Support" },
  { icon: SvgOrganization, text: "Permission Inheritance" },
  { icon: SvgKey, text: "OIDC/SAML SSO" },
  { icon: SvgLock, text: "Encryption of Secrets" },
];

const ENTERPRISE_FEATURES: PlanFeature[] = [
  { icon: SvgHeadsetMic, text: "Priority Support" },
  { icon: SvgPaintBrush, text: "White-labeling" },
  { icon: SvgFileText, text: "Enterprise SLAs" },
];

// ----------------------------------------------------------------------------
// PlanCard (inlined)
// ----------------------------------------------------------------------------

function PlanCard({
  icon: Icon,
  title,
  pricing,
  description,
  buttonLabel,
  buttonIcon: ButtonIcon,
  onClick,
  href,
  features,
  featuresPrefix,
  isCurrentPlan,
  hideFeatures,
}: PlanConfig & { hideFeatures?: boolean }) {
  return (
    <Card
      padding={0}
      gap={0}
      alignItems="stretch"
      aria-label={title + " plan card"}
    >
      <Section
        flexDirection="column"
        alignItems="stretch"
        padding={1}
        height="full"
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

        {/* Pricing */}
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
          <Text mainUiBody text03>
            {description}
          </Text>
        </Section>

        {/* Button */}
        <div className="plan-card-button">
          {isCurrentPlan ? (
            <div className="plan-card-current-badge">
              <Text mainUiAction text03>
                Your Current Plan
              </Text>
            </div>
          ) : href ? (
            <Button
              main
              secondary
              href={href}
              target="_blank"
              rel="noopener noreferrer"
            >
              {buttonLabel}
            </Button>
          ) : (
            <Button main primary onClick={onClick} leftIcon={ButtonIcon}>
              {buttonLabel}
            </Button>
          )}
        </div>
      </Section>

      {/* Features */}
      <div
        className="plan-card-features-container"
        data-hidden={hideFeatures ? "true" : "false"}
      >
        <Section
          flexDirection="column"
          alignItems="start"
          justifyContent="start"
          gap={1}
          padding={1}
        >
          <Text mainUiBody text03>
            {featuresPrefix}
          </Text>
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

// ----------------------------------------------------------------------------
// PlansView
// ----------------------------------------------------------------------------

interface PlansViewProps {
  currentPlan?: string;
  hasSubscription?: boolean;
  onCheckout: () => void;
  hideFeatures?: boolean;
}

export default function PlansView({
  currentPlan,
  hasSubscription,
  onCheckout,
  hideFeatures,
}: PlansViewProps) {
  const isBusinessPlan =
    currentPlan?.toLowerCase() === "business" || hasSubscription;

  const plans: PlanConfig[] = [
    {
      icon: SvgUsers,
      title: "Business",
      pricing: "$20",
      description:
        "per seat/month billed annually\nor $25 per seat if billed monthly",
      buttonLabel: isBusinessPlan ? "Get Business Plan" : "Upgrade Plan",
      buttonVariant: "primary",
      buttonIcon: isBusinessPlan ? undefined : SvgArrowUpCircle,
      onClick: onCheckout,
      features: BUSINESS_FEATURES,
      featuresPrefix: "Get more work done with AI for your team.",
      isCurrentPlan: isBusinessPlan,
    },
    {
      icon: SvgOrganization,
      title: "Enterprise",
      description:
        "Flexible pricing & deployment options for large organizations",
      buttonLabel: "Contact Sales",
      buttonVariant: "secondary",
      href: SALES_URL,
      features: ENTERPRISE_FEATURES,
      featuresPrefix: "Everything in Business Plan, plus:",
    },
  ];

  return (
    <Section flexDirection="row" alignItems="stretch" width="full">
      {plans.map((plan) => (
        <PlanCard key={plan.title} {...plan} hideFeatures={hideFeatures} />
      ))}
    </Section>
  );
}
