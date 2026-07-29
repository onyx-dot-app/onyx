import { MessageCard, Text } from "@opal/components";
import { BillingInformation, BillingStatus } from "@/lib/billing/interfaces";
import { useIsTrialingEnterprise } from "@/hooks/useIsTrialingEnterprise";

export function BillingAlerts({
  billingInformation,
}: {
  billingInformation: BillingInformation;
}) {
  const isTrialing = billingInformation.status === BillingStatus.TRIALING;
  const isCancelled = billingInformation.cancel_at_period_end;
  const isExpired = billingInformation.current_period_end
    ? new Date(billingInformation.current_period_end) < new Date()
    : false;
  const noPaymentMethod = !billingInformation.payment_method_enabled;
  const isTrialingEnterprise = useIsTrialingEnterprise();

  const messages: string[] = [];

  if (isExpired) {
    messages.push(
      "Your subscription has expired. Please resubscribe to continue using the service."
    );
  }
  if (isCancelled && !isExpired && billingInformation.current_period_end) {
    messages.push(
      `Your subscription will cancel on ${new Date(
        billingInformation.current_period_end
      ).toLocaleDateString()}. You can resubscribe before this date to remain uninterrupted.`
    );
  }
  if (isTrialing) {
    const trialEndStr = billingInformation.trial_end
      ? new Date(billingInformation.trial_end).toLocaleDateString()
      : "N/A";
    messages.push(
      isTrialingEnterprise
        ? `You're trialing Enterprise features. Your trial ends on ${trialEndStr}. After that, your workspace will revert to the Business plan.`
        : `You're currently on a trial. Your trial ends on ${trialEndStr}.`
    );
  }
  if (noPaymentMethod) {
    messages.push(
      "You currently have no payment method on file. Please add one to avoid service interruption."
    );
  }

  if (messages.length === 0) return null;

  const isDestructive = isExpired || noPaymentMethod;

  return (
    <MessageCard
      variant={isDestructive ? "error" : "info"}
      title={
        isDestructive ? "Important Subscription Notice" : "Subscription Notice"
      }
      bottomChildren={
        <ul className="list-disc list-inside space-y-1 px-2 pb-2">
          {messages.map((msg, idx) => (
            <Text key={idx} as="li" font="main-ui-body" color="text-03">
              {msg}
            </Text>
          ))}
        </ul>
      }
    />
  );
}
