"use client";

import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import { SvgWallet, SvgCalendar, SvgExternalLink } from "@opal/icons";
import { BillingInformation } from "@/lib/billing/interfaces";
import { createCustomerPortalSession } from "@/lib/billing/actions";
import { humanReadableFormatShort } from "@/lib/time";

interface PaymentSectionProps {
  billing: BillingInformation;
}

export default function PaymentSection({ billing }: PaymentSectionProps) {
  const handleUpdatePayment = async () => {
    try {
      const response = await createCustomerPortalSession();
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (error) {
      console.error("Failed to open customer portal:", error);
    }
  };

  const handleViewInvoice = async () => {
    try {
      const response = await createCustomerPortalSession();
      if (response.url) {
        window.location.href = response.url;
      }
    } catch (error) {
      console.error("Failed to open customer portal:", error);
    }
  };

  // Only show if payment method is enabled
  if (!billing.payment_method_enabled) {
    return null;
  }

  const lastPaymentDate = humanReadableFormatShort(
    billing.current_period_start
  );

  return (
    <Section gap={0.75} alignItems="start" height="auto" width="full">
      <Text mainContentEmphasis>Payment</Text>

      <Section flexDirection="row" gap={0.5} alignItems="stretch" height="auto">
        {/* Payment Method Card */}
        <Card className="billing-payment-card">
          <Section
            flexDirection="row"
            justifyContent="between"
            alignItems="start"
            height="auto"
          >
            <Section
              flexDirection="row"
              gap={0.5}
              justifyContent="start"
              alignItems="center"
              height="auto"
              width="auto"
            >
              <SvgWallet className="w-5 h-5 stroke-text-04" />
              <Section
                gap={0.125}
                alignItems="start"
                height="auto"
                width="auto"
              >
                <Text mainContentEmphasis>Payment method</Text>
                <Text secondaryBody text03>
                  Managed via Stripe
                </Text>
              </Section>
            </Section>
            <Button
              main
              tertiary
              onClick={handleUpdatePayment}
              rightIcon={SvgExternalLink}
            >
              Update
            </Button>
          </Section>
        </Card>

        {/* Last Payment Card */}
        {lastPaymentDate && (
          <Card className="billing-payment-card">
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="start"
              height="auto"
            >
              <Section
                flexDirection="row"
                gap={0.5}
                justifyContent="start"
                alignItems="center"
                height="auto"
                width="auto"
              >
                <SvgCalendar className="w-5 h-5 stroke-text-04" />
                <Section
                  gap={0.125}
                  alignItems="start"
                  height="auto"
                  width="auto"
                >
                  <Text mainContentEmphasis>{lastPaymentDate}</Text>
                  <Text secondaryBody text03>
                    Last payment
                  </Text>
                </Section>
              </Section>
              <Button
                main
                tertiary
                onClick={handleViewInvoice}
                rightIcon={SvgExternalLink}
              >
                View Invoice
              </Button>
            </Section>
          </Card>
        )}
      </Section>
    </Section>
  );
}
