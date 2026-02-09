import React from "react";
import { InfoItem } from "./InfoItem";
import { statusToDisplay, BillingInformation } from "@/lib/billing";
import { formatDateShort } from "@/lib/dateUtils";

interface SubscriptionSummaryProps {
  billingInformation: BillingInformation;
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
      <InfoItem
        title="Seats"
        value={billingInformation.seats?.toString() ?? "—"}
      />
      <InfoItem
        title="Billing Start"
        value={formatDateShort(billingInformation.current_period_start)}
      />
      <InfoItem
        title="Billing End"
        value={formatDateShort(billingInformation.current_period_end)}
      />
    </div>
  );
}
