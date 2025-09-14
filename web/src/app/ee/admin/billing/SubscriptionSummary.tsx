import React from "react";
("use client");

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import { InfoItem } from "./InfoItem";
import { statusToDisplay } from "./utils";

interface SubscriptionSummaryProps {
  billingInformation: any;
}

export function SubscriptionSummary({
  billingInformation,
}: SubscriptionSummaryProps) {
  const { t } = useTranslation();
  return (
    <div className="grid grid-cols-2 gap-4">
      <InfoItem
        title={t(k.SUBSCRIPTION_STATUS)}
        value={statusToDisplay(billingInformation.status)}
      />

      <InfoItem
        title={t(k.SEATS)}
        value={billingInformation.seats.toString()}
      />
      <InfoItem
        title={t(k.BILLING_START)}
        value={new Date(
          billingInformation.current_period_start
        ).toLocaleDateString()}
      />

      <InfoItem
        title={t(k.BILLING_END)}
        value={new Date(
          billingInformation.current_period_end
        ).toLocaleDateString()}
      />
    </div>
  );
}
