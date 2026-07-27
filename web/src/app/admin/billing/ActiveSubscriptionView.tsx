"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import { Button } from "@opal/components";
import { Content } from "@opal/layouts";
import { markdown } from "@opal/utils";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import { SvgCheckCircle } from "@opal/icons";
import { claimLicense } from "@/lib/billing/svc";
import { formatDateShort } from "@/lib/dateUtils";
import type { BillingInformation } from "@/lib/billing/interfaces";

interface ActiveSubscriptionViewProps {
  billing?: BillingInformation;
  isSelfHosted: boolean;
  onSynced: () => void;
  onViewDetails: () => void;
}

/**
 * Shown in place of the checkout flow when the account already has a live
 * subscription: with one, a new checkout can only 409 on the control plane's
 * duplicate-subscription guard. Renewals happen automatically in Stripe, so
 * the only useful actions are syncing the license and viewing billing details.
 */
export default function ActiveSubscriptionView({
  billing,
  isSelfHosted,
  onSynced,
  onViewDetails,
}: ActiveSubscriptionViewProps) {
  const [isSyncing, setIsSyncing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSync = async () => {
    setIsSyncing(true);
    setError(null);
    try {
      await claimLicense();
      onSynced();
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to sync your license"
      );
    } finally {
      setIsSyncing(false);
    }
  };

  const nextBillingDate = billing?.current_period_end
    ? formatDateShort(billing.current_period_end)
    : null;

  const description = [
    "It renews automatically, so there is nothing to buy.",
    nextBillingDate && `Your next billing date is **${nextBillingDate}**.`,
    isSelfHosted &&
      "A new license file is issued automatically each billing period. " +
        "If this instance reports an expired license, sync it now.",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <Card padding={0} gap={0} alignItems="stretch">
      <Section alignItems="start" padding={1} height="auto">
        <Content
          sizePreset="section"
          variant="heading"
          icon={SvgCheckCircle}
          title="Your subscription is active"
          description={markdown(description)}
        />
      </Section>

      <Section
        flexDirection="row"
        alignItems="center"
        justifyContent="between"
        padding={1}
        height="auto"
      >
        {error ? (
          <Text secondaryBody className="billing-error-text">
            {error}
          </Text>
        ) : (
          // Empty div to maintain space-between alignment
          <div />
        )}
        <Section
          flexDirection="row"
          gap={0.5}
          width="fit"
          height="auto"
          justifyContent="end"
        >
          {isSelfHosted && (
            <Button
              prominence="secondary"
              disabled={isSyncing}
              onClick={handleSync}
            >
              {isSyncing ? "Syncing..." : "Sync License"}
            </Button>
          )}
          <Button onClick={onViewDetails}>View Billing Details</Button>
        </Section>
      </Section>
    </Card>
  );
}
