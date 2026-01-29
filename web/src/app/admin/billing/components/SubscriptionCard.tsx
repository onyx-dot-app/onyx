"use client";

import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgUsers, SvgExternalLink } from "@opal/icons";
import { BillingInformation } from "@/lib/billing/interfaces";
import { createCustomerPortalSession } from "@/lib/billing/actions";
import { formatDateShort } from "@/lib/dateUtils";

interface SubscriptionCardProps {
  billing: BillingInformation;
  onViewPlans: () => void;
}

export default function SubscriptionCard({
  billing,
  onViewPlans,
}: SubscriptionCardProps) {
  const planName = billing.plan_type
    ? `${billing.plan_type.charAt(0).toUpperCase()}${billing.plan_type.slice(
        1
      )} Plan`
    : "Business Plan";

  const nextPaymentDate = formatDateShort(billing.current_period_end);

  const isExpired =
    billing.status === "expired" || billing.status === "cancelled";
  const isCanceling = billing.cancel_at_period_end;

  let subtitle: string;
  if (isExpired) {
    subtitle = "Expired";
  } else if (isCanceling) {
    subtitle = `Valid until ${nextPaymentDate}`;
  } else {
    subtitle = `Next payment on ${nextPaymentDate}`;
  }

  const handleManagePlan = async () => {
    try {
      const response = await createCustomerPortalSession();
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (error) {
      console.error("Failed to open customer portal:", error);
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
          <Button
            main
            primary
            onClick={handleManagePlan}
            rightIcon={SvgExternalLink}
          >
            Manage Plan
          </Button>
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
