"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import { SvgUsers, SvgShield } from "@opal/icons";
import PlanCard from "./PlanCard";
import FooterLinks from "./FooterLinks";
import LicenseInput from "./LicenseInput";
import { createCheckoutSession } from "@/lib/billing/actions";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

const SALES_URL = "https://www.onyx.app/contact";

const BUSINESS_FEATURES = [
  "Enterprise Search",
  "Query History & Usage Dashboard",
  "On-Premise Deployments",
  "Region-Specific Deployments",
  "RBAC Support",
  "Permission Inheritance",
  "OIDC/SAML SSO",
  "Encryption of Secrets",
];

const ENTERPRISE_FEATURES = [
  "Priority Support",
  "White-labeling",
  "Enterprise SLAs",
];

interface PlansProps {
  currentPlan?: string;
  onLicenseActivated?: () => void;
}

export default function Plans({ currentPlan, onLicenseActivated }: PlansProps) {
  const [showLicenseInput, setShowLicenseInput] = useState(false);
  const isBusinessPlan = currentPlan?.toLowerCase() === "business";
  const isSelfHosted = !NEXT_PUBLIC_CLOUD_ENABLED;

  const handleGetBusinessPlan = async () => {
    try {
      const response = await createCheckoutSession({
        billing_period: "annual",
      });
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (error) {
      console.error("Failed to create checkout session:", error);
    }
  };

  const handleActivateLicense = () => {
    setShowLicenseInput(true);
  };

  const handleCancelLicenseInput = () => {
    setShowLicenseInput(false);
  };

  const handleLicenseSuccess = () => {
    setShowLicenseInput(false);
    onLicenseActivated?.();
  };

  return (
    <Section gap={2} height="auto">
      {/* Plan cards */}
      <Section flexDirection="row" gap={1} alignItems="stretch" height="auto">
        <PlanCard
          icon={SvgUsers}
          title="Business"
          price={{
            main: "$20 per seat/month billed annually",
            sub: "or $25 per seat if billed monthly",
          }}
          features={BUSINESS_FEATURES}
          ctaLabel="Get Business Plan"
          onCtaClick={handleGetBusinessPlan}
          isCurrentPlan={isBusinessPlan}
        />

        <PlanCard
          icon={SvgShield}
          title="Enterprise"
          description="Flexible pricing & deployment options for large organizations"
          features={ENTERPRISE_FEATURES}
          featuresPrefix="Everything in Business Plan, plus:"
          ctaLabel="Contact Sales"
          ctaHref={SALES_URL}
          isExternal
        />
      </Section>

      {/* License input - self-hosted only */}
      {isSelfHosted && showLicenseInput && (
        <LicenseInput
          onCancel={handleCancelLicenseInput}
          onSuccess={handleLicenseSuccess}
        />
      )}

      {/* Footer links */}
      <FooterLinks
        hasSubscription={!!currentPlan}
        onActivateLicense={isSelfHosted ? handleActivateLicense : undefined}
      />
    </Section>
  );
}
