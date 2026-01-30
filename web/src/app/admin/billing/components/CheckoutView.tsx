"use client";

import { useState, useMemo } from "react";
import { Section } from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import Separator from "@/refresh-components/Separator";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { SvgUsers, SvgCheck } from "@opal/icons";
import { createCheckoutSession } from "@/lib/billing/svc";
import { useUser } from "@/components/user/UserProvider";
import * as InputLayouts from "@/layouts/input-layouts";
import { formatDateShort } from "@/lib/dateUtils";
import type { PlanType } from "@/lib/billing/interfaces";
interface BillingOptionProps {
  selected: boolean;
  onClick: () => void;
  title: string;
  price: number;
  badge?: string;
}

function BillingOption({
  selected,
  onClick,
  title,
  price,
  badge,
}: BillingOptionProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="billing-option"
      data-selected={selected}
    >
      <Section
        flexDirection="row"
        gap={0.5}
        height="fit"
        justifyContent="between"
        alignItems="start"
      >
        <Section
          alignItems="start"
          justifyContent="center"
          gap={0}
          height="fit"
          width="fit"
        >
          <Text mainUiAction className="billing-option-title">
            {title}
          </Text>
          <div className="billing-option-price">
            <Text mainContentEmphasis text04>
              ${price}
            </Text>
            <Text secondaryBody text03 nowrap>
              per seat/month
            </Text>
          </div>
        </Section>
        {selected && badge && (
          <Section
            flexDirection="row"
            gap={0.25}
            alignItems="center"
            justifyContent="end"
            width="fit"
            height="fit"
          >
            <Text secondaryAction className="billing-option-badge">
              {badge}
            </Text>
            <SvgCheck className="billing-option-check" />
          </Section>
        )}
      </Section>
    </button>
  );
}

interface CheckoutViewProps {
  onAdjustPlan: () => void;
}

export default function CheckoutView({ onAdjustPlan }: CheckoutViewProps) {
  const { user } = useUser();
  const [billingPeriod, setBillingPeriod] = useState<PlanType>("monthly");
  const [seats, setSeats] = useState("5");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const monthlyPrice = 25;
  const annualPrice = 20;
  let annualPriceSelected = Boolean(billingPeriod === "annual");

  // Calculate trial end date (1 month from now)
  const trialEndDate = useMemo(() => {
    const date = new Date();
    date.setMonth(date.getMonth() + 1);
    return formatDateShort(date.toISOString());
  }, []);

  const handleSeatsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    if (value === "" || /^\d+$/.test(value)) {
      setSeats(value);
    }
  };

  const getSeatsValue = () => {
    const num = parseInt(seats);
    return isNaN(num) || num < 1 ? 1 : num;
  };

  const handleSubmit = async () => {
    setIsSubmitting(true);
    setError(null);

    try {
      const response = await createCheckoutSession({
        billing_period: billingPeriod,
        seats: getSeatsValue(),
        email: user?.email,
      });

      if (response.stripe_checkout_url) {
        window.location.href = response.stripe_checkout_url;
      } else {
        throw new Error("Invalid response from checkout session");
      }
    } catch (err) {
      console.error("Error creating checkout session:", err);
      setError(
        err instanceof Error ? err.message : "Failed to create checkout session"
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <Card padding={0} alignItems="stretch">
      {/* Header */}
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        padding={1}
        height="auto"
      >
        <Section
          flexDirection="column"
          alignItems="start"
          gap={0.25}
          height="auto"
          width="fit"
        >
          <SvgUsers size={24} />
          <Text headingH2 text04>
            Business
          </Text>
        </Section>
        <Button secondary onClick={onAdjustPlan}>
          Adjust Plan
        </Button>
      </Section>

      {/* Content area */}
      <div className="billing-content-area">
        <Section
          flexDirection="column"
          alignItems="stretch"
          gap={1}
          padding={1}
          height="auto"
        >
          {/* Billing Cycle Row */}
          <InputLayouts.Horizontal
            title="Billing Cycle"
            description="after your 1-month free trial"
            cursorPointer={false}
          >
            <Section
              flexDirection="row"
              gap={0.25}
              width="fit"
              height="auto"
              justifyContent="start"
            >
              <BillingOption
                selected={billingPeriod === "monthly"}
                onClick={() => setBillingPeriod("monthly")}
                title="Monthly"
                price={monthlyPrice}
              />
              <BillingOption
                selected={billingPeriod === "annual"}
                onClick={() => setBillingPeriod("annual")}
                title="Annual"
                price={annualPrice}
                badge="Save 20%"
              />
            </Section>
          </InputLayouts.Horizontal>

          <Separator noPadding />

          {/* Seats Row */}
          <InputLayouts.Horizontal
            title="Seats"
            description="applies to both user accounts and Slack integration accounts."
            cursorPointer={false}
          >
            <InputTypeIn
              value={seats}
              onChange={handleSeatsChange}
              showClearButton={false}
            />
          </InputLayouts.Horizontal>
        </Section>
      </div>

      {/* Footer */}
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
        ) : !annualPriceSelected ? (
          <Text secondaryBody text03>
            You will be billed on{" "}
            <Text secondaryBody text04>
              {trialEndDate}
            </Text>{" "}
            After your 1-month free trial ends.
          </Text>
        ) : (
          <div></div>
        )}
        <Button main primary onClick={handleSubmit} disabled={isSubmitting}>
          {isSubmitting ? "Loading..." : "Continue to Payment"}
        </Button>
      </Section>
    </Card>
  );
}
