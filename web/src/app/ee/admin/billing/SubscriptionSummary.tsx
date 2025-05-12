import React from "react";
import { InfoItem } from "./InfoItem";
import { statusToDisplay } from "@/lib/billing/utils";

interface SubscriptionSummaryProps {
  billingInformation: any;
}

export function SubscriptionSummary({
  billingInformation,
}: SubscriptionSummaryProps) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <InfoItem
        title="Subscription Status"
        value={statusToDisplay(billingInformation.status)}
      />
      <InfoItem title="Seats" value={billingInformation.seats.toString()} />
      <InfoItem
        title="Billing Start"
        value={new Date(
          billingInformation.current_period_start
        ).toLocaleDateString()}
      />
      <InfoItem
        title="Billing End"
        value={new Date(
          billingInformation.current_period_end
        ).toLocaleDateString()}
      />
    </div>
  );
}
