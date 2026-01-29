"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import Card from "@/refresh-components/cards/Card";
import Separator from "@/refresh-components/Separator";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { SvgUsers, SvgCheck } from "@opal/icons";
import { cn } from "@/lib/utils";
import { createCheckoutSession } from "@/lib/billing/actions";
import { useUser } from "@/components/user/UserProvider";
import * as InputLayouts from "@/layouts/input-layouts";

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
      onClick={onClick}
      className={cn(
        "w-[200px] min-w-[160px] p-1.5 rounded-08 border text-left transition-colors",
        selected
          ? "border-action-link-05 bg-action-link-01"
          : "border-border-01 bg-background-neutral-00 hover:border-border-02"
      )}
    >
      <Section
        flexDirection="row"
        gap={0.25}
        padding={0.125}
        height="fit"
        justifyContent="start"
        alignItems="start"
      >
        <Section
          alignItems="start"
          justifyContent="center"
          gap={0}
          height="fit"
        >
          <Text
            mainUiAction
            className={cn(selected ? "text-action-link-05" : "text-text-04")}
          >
            {title}
          </Text>
          <div className="flex flex-row gap-1 items-baseline">
            <Text mainContentEmphasis text04>
              ${price}
            </Text>
            <Text secondaryBody text03 className="whitespace-nowrap">
              per seat/month
            </Text>
          </div>
        </Section>
        {selected && badge && (
          <Section
            flexDirection="row"
            gap={0.375}
            alignItems="center"
            justifyContent="end"
            width="fit"
            height="fit"
          >
            <Text secondaryAction className="text-action-link-05">
              {badge}
            </Text>
            <SvgCheck className="w-4 h-4 stroke-action-link-05" />
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
  const [billingPeriod, setBillingPeriod] = useState<"monthly" | "annual">(
    "annual"
  );
  const [seats, setSeats] = useState("5");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const monthlyPrice = 25;
  const annualPrice = 20;

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
    <div className="w-full">
      <Card padding={0}>
        {/* Header */}
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          padding={1}
          height="fit"
        >
          <div className="flex flex-col gap-1">
            <SvgUsers size={24} className="stroke-text-04" />
            <Text headingH2 text04>
              Business
            </Text>
          </div>
          <Button secondary onClick={onAdjustPlan}>
            Adjust Plan
          </Button>
        </Section>

        {/* Content area */}
        <div className="bg-background-tint-01 w-full">
          <Section
            alignItems="start"
            justifyContent="center"
            gap={1}
            padding={1}
            height="fit"
            width="full"
          >
            {/* Billing Row */}
            <Section
              flexDirection="row"
              alignItems="start"
              height="fit"
              justifyContent="start"
              width="full"
            >
              <div className="flex flex-1 max-w-[480px] pr-2 pt-2">
                <Section alignItems="start" gap={0} height="fit">
                  <Text mainUiAction text04>
                    Billing Cycle
                  </Text>
                  <Text secondaryBody text03>
                    after your 1-month free trial
                  </Text>
                </Section>
              </div>
              <Section
                flexDirection="row"
                gap={0.25}
                width="fit"
                height="fit"
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
            </Section>

            <Separator noPadding />

            {/* Seats Row */}
            {/* Use  */}
            <InputLayouts.Horizontal
              // name="seats"
              title="Seats"
              description="applies to both user accounts and Slack integration accounts."
            >
              <InputTypeIn
                type="number"
                min={1}
                value={seats}
                onChange={handleSeatsChange}
                showClearButton={false}
              />
            </InputLayouts.Horizontal>
            {/* <Section
              flexDirection="row"
              alignItems="start"
              justifyContent="between"
              height="fit"
              width="full"
            >
              <div className="flex flex-1 max-w-[480px] pr-2">
                <Section alignItems="start" gap={0} height="fit">
                  <Text mainUiAction text04>
                    Seats
                  </Text>
                  <Text secondaryBody text03>
                    applies to both user accounts and Slack integration
                    accounts.
                  </Text>
                </Section>
              </div>
              <div className="flex flex-1 max-w-[240px]">
                <InputTypeIn
                  type="number"
                  min={1}
                  value={seats}
                  onChange={handleSeatsChange}
                  showClearButton={false}
                  className="min-w-[160px]"
                />
              </div>
            </Section> */}
          </Section>
        </div>

        {/* Footer */}
        <Section
          flexDirection="row"
          alignItems="center"
          justifyContent="end"
          gap={0.5}
          padding={1}
          height="fit"
          width="full"
        >
          <div className="flex flex-1 items-center">
            {error ? (
              <Text secondaryBody className="text-status-error-05">
                {error}
              </Text>
            ) : (
              <Text secondaryBody text03>
                You will be billed after the free trial ends.
              </Text>
            )}
          </div>
          <div className="shrink-0">
            <Button main primary onClick={handleSubmit} disabled={isSubmitting}>
              {isSubmitting ? "Loading..." : "Continue to Payment"}
            </Button>
          </div>
        </Section>
      </Card>
    </div>
  );
}
