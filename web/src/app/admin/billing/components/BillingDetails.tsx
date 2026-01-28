"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import ExpirationBanner from "./ExpirationBanner";
import SubscriptionCard from "./SubscriptionCard";
import SeatsCard from "./SeatsCard";
import PaymentSection from "./PaymentSection";
import LicenseInput from "./LicenseInput";
import FooterLinks from "./FooterLinks";
import { humanReadableFormatShort } from "@/lib/time";

interface BillingDetailsProps {
  billing: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  onRefresh?: () => void;
}

function getExpirationState(
  billing: BillingInformation,
  license?: LicenseStatus
) {
  // Check license expiration for self-hosted
  if (license?.expires_at) {
    const expiresAt = new Date(license.expires_at);
    const now = new Date();
    const daysRemaining = Math.ceil(
      (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (daysRemaining <= 0 || license.status === "expired") {
      return {
        variant: "error" as const,
        daysRemaining: 0,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }

    if (daysRemaining <= 30) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }
  }

  // Check billing expiration for cloud
  if (billing.cancel_at_period_end && billing.current_period_end) {
    const expiresAt = new Date(billing.current_period_end);
    const now = new Date();
    const daysRemaining = Math.ceil(
      (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (daysRemaining <= 0) {
      return {
        variant: "error" as const,
        daysRemaining: 0,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }

    if (daysRemaining <= 30) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }
  }

  if (billing.status === "expired" || billing.status === "cancelled") {
    return {
      variant: "error" as const,
      daysRemaining: 0,
      expirationDate: "",
    };
  }

  return null;
}

export default function BillingDetails({
  billing,
  license,
  onViewPlans,
  onRefresh,
}: BillingDetailsProps) {
  const [showLicenseInput, setShowLicenseInput] = useState(false);
  const isSelfHosted = !NEXT_PUBLIC_CLOUD_ENABLED;

  const expirationState = getExpirationState(billing, license);

  const handleActivateLicense = () => {
    setShowLicenseInput(true);
  };

  const handleCancelLicenseInput = () => {
    setShowLicenseInput(false);
  };

  const handleLicenseSuccess = () => {
    setShowLicenseInput(false);
    onRefresh?.();
  };

  return (
    <Section gap={1} height="auto">
      {/* Expiration banner */}
      {expirationState && (
        <ExpirationBanner
          variant={expirationState.variant}
          daysRemaining={expirationState.daysRemaining}
          expirationDate={expirationState.expirationDate}
        />
      )}

      {/* Subscription card */}
      <SubscriptionCard billing={billing} onViewPlans={onViewPlans} />

      {/* Seats card */}
      <SeatsCard billing={billing} license={license} onRefresh={onRefresh} />

      {/* Payment section - only show if has payment info */}
      {billing.payment_method_enabled && <PaymentSection billing={billing} />}

      {/* License input - self-hosted only */}
      {isSelfHosted && showLicenseInput && (
        <LicenseInput
          onCancel={handleCancelLicenseInput}
          onSuccess={handleLicenseSuccess}
        />
      )}

      {/* Footer links */}
      <FooterLinks
        hasSubscription
        onActivateLicense={isSelfHosted ? handleActivateLicense : undefined}
      />
    </Section>
  );
}
