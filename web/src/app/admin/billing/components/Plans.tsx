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

const SALES_URL = "https://www.onyx.app/contact-sales";

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

  return (
    <div className="w-full flex flex-row gap-4 items-stretch">
      <PlanCard
        icon={SvgUsers}
        title="Business"
        pricing={{
          amount: "$20",
          details: [
            "per seat/month billed annually",
            "or $25 per seat if billed monthly",
          ],
        }}
        button={{
          label: "Get Business Plan",
          variant: "primary",
          onClick: onCheckout,
        }}
        features={BUSINESS_FEATURES}
        featuresPrefix="Get more work done with AI for your team."
        isCurrentPlan={isBusinessPlan}
        hideFeatures={hideFeatures}
      />
      <PlanCard
        icon={SvgOrganization}
        title="Enterprise"
        description="Flexible pricing & deployment options for large organizations"
        button={{
          label: "Contact Sales",
          variant: "secondary",
          href: SALES_URL,
        }}
        features={ENTERPRISE_FEATURES}
        featuresPrefix="Everything in Business Plan, plus:"
        hideFeatures={hideFeatures}
      />
    </div>
  );
}
