import i18n from "i18next";
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
    messages.push(
      "Ваша подписка истекла. Пожалуйста, подпишитесь повторно, чтобы продолжить пользоваться сервисом."
    );
  }
  if (isCancelled && !isExpired) {
    messages.push(
      `Ваша подписка будет отменена ${new Date(
        billingInformation.current_period_end
      ).toLocaleDateString()}. Вы можете подписаться повторно до этой даты, чтобы не прерываться.`
    );
  }
  if (isTrialing) {
    messages.push(
      `В настоящее время у вас пробный период. Ваш пробный период заканчивается ${
        billingInformation.trial_end
          ? new Date(billingInformation.trial_end).toLocaleDateString()
          : "N/A"
      }.`
    );
  }
  if (noPaymentMethod) {
    messages.push(
      "В настоящее время у вас нет зарегистрированного способа оплаты. Пожалуйста, добавьте его, чтобы избежать перерыва в обслуживании."
    );
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
