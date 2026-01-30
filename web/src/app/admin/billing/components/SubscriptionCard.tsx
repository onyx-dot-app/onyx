"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgUsers, SvgExternalLink, SvgArrowRight } from "@opal/icons";
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import {
  createCustomerPortalSession,
  resetStripeConnection,
} from "@/lib/billing/svc";
import { formatDateShort } from "@/lib/dateUtils";

interface SubscriptionCardProps {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  /** Disable the Manage Plan button (air-gapped or Stripe error) */
  disabled?: boolean;
  /** Called after successful reconnection to refresh data */
  onReconnect?: () => Promise<void>;
}

export default function SubscriptionCard({
  billing,
  license,
  onViewPlans,
  disabled,
  onReconnect,
}: SubscriptionCardProps) {
  const [isReconnecting, setIsReconnecting] = useState(false);

  // Plan name is always "Business Plan" for now (plan_type is billing period, not tier)
  const planName = "Business Plan";

  // Derive expiration date from billing or license
  const expirationDate = billing?.current_period_end ?? license?.expires_at;
  const formattedDate = formatDateShort(expirationDate);

  // Determine status
  const isExpiredFromBilling =
    billing?.status === "expired" || billing?.status === "cancelled";
  const isExpiredFromLicense =
    license?.status === "expired" ||
    license?.status === "gated_access" ||
    (license?.expires_at && new Date(license.expires_at) < new Date());
  const isExpired = isExpiredFromBilling || isExpiredFromLicense;

  const isCanceling = billing?.cancel_at_period_end;

  let subtitle: string;
  if (isExpired) {
    subtitle = `Expired on ${formattedDate}`;
  } else if (isCanceling) {
    subtitle = `Valid until ${formattedDate}`;
  } else if (billing) {
    subtitle = `Next payment on ${formattedDate}`;
  } else {
    // License-only mode
    subtitle = `Valid until ${formattedDate}`;
  }

  const handleManagePlan = async () => {
    try {
      const response = await createCustomerPortalSession({
        return_url: `${window.location.origin}/admin/billing?portal_return=true`,
      });
      if (response.stripe_customer_portal_url) {
        window.location.href = response.stripe_customer_portal_url;
      }
    } catch (error) {
      console.error("Failed to open customer portal:", error);
    }
  };

  const handleReconnect = async () => {
    setIsReconnecting(true);
    try {
      await resetStripeConnection();
      await onReconnect?.();
    } catch (error) {
      console.error("Failed to reconnect to Stripe:", error);
    } finally {
      setIsReconnecting(false);
    }
  };

  return (
    <Card>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        height="auto"
      >
        {/* Left side - Icon and plan info */}
        <Section gap={0.25} alignItems="start" height="auto" width="auto">
          <SvgUsers className="w-5 h-5 stroke-text-03" />
          <Text headingH3Muted text04>
            {planName}
          </Text>
          <Text secondaryBody text03>
            {subtitle}
          </Text>
        </Section>

        {/* Right side - Actions */}
        <Section
          flexDirection="column"
          gap={0.25}
          alignItems="end"
          height="auto"
          width="fit"
        >
          {disabled ? (
            <Button
              main
              secondary
              onClick={handleReconnect}
              rightIcon={SvgArrowRight}
              disabled={isReconnecting}
            >
              {isReconnecting ? "Connecting..." : "Connect to Stripe"}
            </Button>
          ) : (
            <Button
              main
              primary
              onClick={handleManagePlan}
              rightIcon={SvgExternalLink}
            >
              Manage Plan
            </Button>
          )}
          <Button tertiary onClick={onViewPlans} className="billing-text-link">
            <Text secondaryBody text03>
              View Plan Details
            </Text>
          </Button>
        </Section>
      </Section>
    </Card>
  );
}
