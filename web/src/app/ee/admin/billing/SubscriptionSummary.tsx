import React from "react";
import { InfoItem } from "./InfoItem";
import { statusToDisplay } from "./utils";

interface SubscriptionSummaryProps {
  billingInformation: any;
}

export function SubscriptionSummary({
  billingInformation,
}: SubscriptionSummaryProps) {
  return (
    <div className="grid grid-cols-2 gap-4">
      <InfoItem
        title="Статус подписки"
        value={statusToDisplay(billingInformation.status)}
      />

      <InfoItem title="Места" value={billingInformation.seats.toString()} />
      <InfoItem
        title="Начало выставления счетов"
        value={new Date(
          billingInformation.current_period_start
        ).toLocaleDateString()}
      />

      <InfoItem
        title="Окончание выставления счетов"
        value={new Date(
          billingInformation.current_period_end
        ).toLocaleDateString()}
      />
    </div>
  );
}
