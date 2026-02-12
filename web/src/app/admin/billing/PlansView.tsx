"use client";

import {
  SvgDashboard,
  SvgHistory,
  SvgFiles,
  SvgGlobe,
  SvgHardDrive,
  SvgHeadsetMic,
  SvgKey,
  SvgLock,
  SvgPaintBrush,
  SvgOrganization,
  SvgServer,
  SvgShield,
  SvgSliders,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import "@/app/admin/billing/billing.css";
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
  { icon: SvgFiles, text: "Inherit Document Permissions" },
  { icon: SvgHistory, text: "Query History and Usage Dashboard" },
  { icon: SvgShield, text: "Role Based Access Control (RBAC)" },
  { icon: SvgLock, text: "Encryption of Secrets" },
  { icon: SvgKey, text: "Service Account API Keys" },
  { icon: SvgHardDrive, text: "Self-hosting (Optional)" },
  { icon: SvgPaintBrush, text: "Custom Theming" },
];

const ENTERPRISE_FEATURES: PlanFeature[] = [
  { icon: SvgUsers, text: "SCIM / Group Sync" },
  { icon: SvgDashboard, text: "Full White-labeling" },
  { icon: SvgUserManage, text: "Custom Roles and Permissions" },
  { icon: SvgSliders, text: "Configurable Usage Limits" },
  { icon: SvgServer, text: "Custom Deployments" },
  { icon: SvgGlobe, text: "Region-Specific Data Processing" },
  { icon: SvgHeadsetMic, text: "Enterprise SLAs and Priority Support" },
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
      className="plan-card"
    >
      <Section
        flexDirection="column"
        alignItems="stretch"
        padding={1}
        height="fit"
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
          <Text
            secondaryBody
            text03
            className={
              pricing ? "whitespace-pre-line" : "whitespace-pre-line min-h-9"
            }
          >
            {description}
          </Text>
        </Section>

        {/* Button */}
        <div className="plan-card-button">
          {isCurrentPlan ? (
            <Button tertiary transient className="pointer-events-none">
              <Text mainUiAction text03>
                Your Current Plan
              </Text>
            </Button>
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
                  <feature.icon size={16} className="stroke-text-03" />
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
  hasSubscription?: boolean;
  onCheckout: () => void;
  hideFeatures?: boolean;
}

export default function PlansView({
  hasSubscription,
  onCheckout,
  hideFeatures,
}: PlansViewProps) {
  const plans: PlanConfig[] = [
    {
      icon: SvgUsers,
      title: "Business",
      pricing: "$20",
      description:
        "per seat/month billed annually\nor $25 per seat if billed monthly",
      buttonLabel: "Get Business Plan",
      buttonVariant: "primary",
      onClick: onCheckout,
      features: BUSINESS_FEATURES,
      featuresPrefix: "Get more work done with AI for your team.",
      isCurrentPlan: hasSubscription,
    },
    {
      icon: SvgOrganization,
      title: "Enterprise",
      description:
        "Flexible pricing & deployment options\nfor large organizations",
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
