import React from "react";
import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
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
        title={i18n.t(k.SUBSCRIPTION_STATUS)}
        value={statusToDisplay(billingInformation.status)}
      />

      <InfoItem
        title={i18n.t(k.SEATS)}
        value={billingInformation.seats.toString()}
      />
      <InfoItem
        title={i18n.t(k.BILLING_START)}
        value={new Date(
          billingInformation.current_period_start
        ).toLocaleDateString()}
      />

      <InfoItem
        title={i18n.t(k.BILLING_END)}
        value={new Date(
          billingInformation.current_period_end
        ).toLocaleDateString()}
      />
    </div>
  );
}
