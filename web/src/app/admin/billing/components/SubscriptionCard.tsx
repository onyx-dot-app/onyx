"use client";

import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgUsers, SvgExternalLink } from "@opal/icons";
import { BillingInformation } from "@/lib/billing/interfaces";
import { createCustomerPortalSession } from "@/lib/billing/actions";
import { humanReadableFormatShort } from "@/lib/time";

interface SubscriptionCardProps {
  billing: BillingInformation;
  onViewPlans: () => void;
}

function getBillingPeriodText(period: string | null): string {
  if (!period) return "";
  return period === "annual" ? "Annual billing" : "Monthly billing";
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

  const billingPeriod = getBillingPeriodText(billing.billing_period);
  const nextPaymentDate = humanReadableFormatShort(billing.current_period_end);

  const isExpired =
    billing.status === "expired" || billing.status === "cancelled";
  const isCanceling = billing.cancel_at_period_end;

  let subtitle: string;
  if (isExpired) {
    subtitle = "Expired";
  } else if (isCanceling) {
    subtitle = `${billingPeriod} \u2022 Valid until ${nextPaymentDate}`;
  } else {
    subtitle = `${billingPeriod} \u2022 Next payment on ${nextPaymentDate}`;
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
        alignItems="center"
        height="auto"
      >
        {/* Left side - Icon and plan info */}
        <Section
          flexDirection="row"
          gap={0.75}
          justifyContent="start"
          alignItems="center"
          height="auto"
          width="auto"
        >
          <SvgUsers className="w-5 h-5 stroke-text-04" />
          <Section gap={0.25} alignItems="start" height="auto" width="auto">
            <Text mainContentEmphasis>{planName}</Text>
            <Text secondaryBody text03>
              {subtitle}
            </Text>
          </Section>
        </Section>

        {/* Right side - Actions */}
        <Section
          flexDirection="row"
          gap={0.5}
          justifyContent="end"
          height="auto"
          width="auto"
        >
          <Button main secondary onClick={handleManagePlan}>
            Manage Plan
          </Button>
          <Button
            main
            tertiary
            onClick={onViewPlans}
            rightIcon={SvgExternalLink}
          >
            View Plan Details
          </Button>
        </Section>
      </Section>
    </Card>
  );
}
