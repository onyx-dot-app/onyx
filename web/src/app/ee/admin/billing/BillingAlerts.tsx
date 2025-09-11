import i18n from "@/i18n/init";
import k from "./../../../../i18n/keys";
import React from "react";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { CircleAlert, Info } from "lucide-react";
import { BillingInformation, BillingStatus } from "./interfaces";

export function BillingAlerts({
  billingInformation,
}: {
  billingInformation: BillingInformation;
}) {
  const isTrialing = billingInformation.status === BillingStatus.TRIALING;
  const isCancelled = billingInformation.cancel_at_period_end;
  const isExpired =
    new Date(billingInformation.current_period_end) < new Date();
  const noPaymentMethod = !billingInformation.payment_method_enabled;

  const messages: string[] = [];

  if (isExpired) {
    messages.push(i18n.t(k.SUBSCRIPTION_EXPIRED_MESSAGE));
  }
  if (isCancelled && !isExpired) {
    messages.push(
      i18n.t(k.SUBSCRIPTION_CANCELLED_MESSAGE_DETAILED, {
        date: new Date(
          billingInformation.current_period_end
        ).toLocaleDateString(),
      })
    );
  }
  if (isTrialing) {
    messages.push(
      i18n.t(k.TRIAL_PERIOD_MESSAGE_DETAILED, {
        date: billingInformation.trial_end
          ? new Date(billingInformation.trial_end).toLocaleDateString()
          : "N/A",
      })
    );
  }
  if (noPaymentMethod) {
    messages.push(i18n.t(k.NO_PAYMENT_METHOD_MESSAGE_DETAILED));
  }

  const variant = isExpired || noPaymentMethod ? "destructive" : "default";

  if (messages.length === 0) return null;

  return (
    <Alert variant={variant}>
      <AlertTitle className="flex items-center space-x-2">
        {variant === "destructive" ? (
          <CircleAlert className="h-4 w-4" />
        ) : (
          <Info className="h-4 w-4" />
        )}
        <span>
          {variant === "destructive"
            ? i18n.t(k.IMPORTANT_SUBSCRIPTION_NOTICE)
            : i18n.t(k.SUBSCRIPTION_NOTICE)}
        </span>
      </AlertTitle>
      <AlertDescription>
        <ul className="list-disc list-inside space-y-1 mt-2">
          {messages.map((msg, idx) => (
            <li key={idx}>{msg}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}
