"use client";

import { useRouter } from "next/navigation";
import { Section } from "@/layouts/general-layouts";
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import ExpirationBanner from "./ExpirationBanner";
import SubscriptionCard from "./SubscriptionCard";
import SeatsCard from "./SeatsCard";
import PaymentSection from "./PaymentSection";
import FooterLinks from "./FooterLinks";
import { humanReadableFormatShort } from "@/lib/time";

interface BillingDetailsProps {
  billing: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  onRefresh?: () => void;
}

// Grace period for data deletion after expiration (30 days)
const GRACE_PERIOD_DAYS = 30;

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
      // Calculate days until deletion from grace period end
      const gracePeriodEnd = license.grace_period_end
        ? new Date(license.grace_period_end)
        : new Date(
            expiresAt.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000
          );
      const daysUntilDeletion = Math.max(
        0,
        Math.ceil(
          (gracePeriodEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
        )
      );

      return {
        variant: "error" as const,
        daysRemaining: 0,
        daysUntilDeletion,
        expirationDate: humanReadableFormatShort(gracePeriodEnd),
      };
    }

    if (daysRemaining <= 14) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }

    // Show info banner for subscriptions expiring within 60 days
    if (daysRemaining <= 60) {
      return {
        variant: "info" as const,
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
      // Calculate days until deletion (grace period after expiration)
      const gracePeriodEnd = new Date(
        expiresAt.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000
      );
      const daysUntilDeletion = Math.max(
        0,
        Math.ceil(
          (gracePeriodEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
        )
      );

      return {
        variant: "error" as const,
        daysRemaining: 0,
        daysUntilDeletion,
        expirationDate: humanReadableFormatShort(gracePeriodEnd),
      };
    }

    if (daysRemaining <= 14) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }

    // Show info banner for subscriptions expiring within 60 days
    if (daysRemaining <= 60) {
      return {
        variant: "info" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }
  }

  if (billing.status === "expired" || billing.status === "cancelled") {
    return {
      variant: "error" as const,
      daysRemaining: 0,
      daysUntilDeletion: GRACE_PERIOD_DAYS,
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
  const router = useRouter();
  const isSelfHosted = !NEXT_PUBLIC_CLOUD_ENABLED;

  const expirationState = getExpirationState(billing, license);

  const handleActivateLicense = () => {
    router.push("/admin/billing/activate" as any);
  };

  return (
    <Section gap={1} height="auto" width="full">
      {/* Expiration banner */}
      {expirationState && (
        <ExpirationBanner
          variant={expirationState.variant}
          daysRemaining={expirationState.daysRemaining}
          expirationDate={expirationState.expirationDate}
          daysUntilDeletion={expirationState.daysUntilDeletion}
        />
      )}

      {/* Subscription card */}
      <SubscriptionCard billing={billing} onViewPlans={onViewPlans} />

      {/* Seats card */}
      <SeatsCard billing={billing} license={license} onRefresh={onRefresh} />

      {/* Payment section - only show if has payment info */}
      {billing.payment_method_enabled && <PaymentSection billing={billing} />}

      {/* Footer links */}
      <FooterLinks
        hasSubscription
        onActivateLicense={isSelfHosted ? handleActivateLicense : undefined}
      />
    </Section>
  );
}
