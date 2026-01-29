"use client";

import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InfoBlock from "@/refresh-components/messages/InfoBlock";
import { SvgWallet, SvgFileText, SvgExternalLink } from "@opal/icons";
import { BillingInformation } from "@/lib/billing/interfaces";
import { createCustomerPortalSession } from "@/lib/billing/actions";
import { formatDateShort } from "@/lib/dateUtils";

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

  const lastPaymentDate = formatDateShort(billing.current_period_start);

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
            <InfoBlock
              icon={SvgWallet}
              title="Visa ending in 1234"
              description="Payment method"
            />
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
              <InfoBlock
                icon={SvgFileText}
                title={lastPaymentDate}
                description="Last payment"
              />
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
