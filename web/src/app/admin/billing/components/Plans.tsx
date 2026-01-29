"use client";

import {
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
import { PlanCard, type PlanFeature } from "./PlanCard";
import { Section } from "../../../../layouts/general-layouts";

const SALES_URL = "https://www.onyx.app/contact-sales";

interface PlansProps {
  currentPlan?: string;
  onCheckout: () => void;
  hideFeatures?: boolean;
}

export default function Plans({
  currentPlan,
  onCheckout,
  hideFeatures,
}: PlansProps) {
  const isBusinessPlan = currentPlan?.toLowerCase() === "business";

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

  const PLANS = [
    {
      icon: SvgUsers,
      title: "Business",
      pricing: "$20",
      description:
        "per seat/month billed annually\nor $25 per seat if billed monthly",
      button: {
        label: "Get Business Plan",
        variant: "primary",
        onClick: onCheckout,
      },
      features: BUSINESS_FEATURES,
      featuresPrefix: "Get more work done with AI for your team.",
      isCurrentPlan: isBusinessPlan,
      hideFeatures: hideFeatures,
    },
    {
      icon: SvgOrganization,
      title: "Enterprise",
      description:
        "Flexible pricing & deployment options for large organizations",
      button: {
        label: "Contact Sales",
        variant: "secondary",
        href: SALES_URL,
      },
      features: ENTERPRISE_FEATURES,
      featuresPrefix: "Everything in Business Plan, plus:",
      hideFeatures: hideFeatures,
    },
  ];

  return (
    <Section flexDirection="row" alignItems="stretch" width="full">
      {PLANS.map((plan) => (
        <PlanCard
          key={plan.title}
          icon={plan.icon}
          title={plan.title}
          pricing={plan.pricing}
          description={plan.description}
          button={{
            label: plan.button.label,
            variant: plan.button.variant as "primary" | "secondary",
            onClick: plan.button.onClick,
            href: plan.button.href,
          }}
          features={plan.features}
          featuresPrefix={plan.featuresPrefix}
          isCurrentPlan={plan.isCurrentPlan}
          hideFeatures={plan.hideFeatures}
        />
      ))}
    </Section>
  );
}
