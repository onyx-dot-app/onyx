"use client";

import Message from "@/refresh-components/messages/Message";

type BannerVariant = "info" | "warning" | "error";

interface ExpirationBannerProps {
  variant: BannerVariant;
  daysRemaining?: number;
  expirationDate?: string;
  /** Days until data deletion (only for expired state) */
  daysUntilDeletion?: number;
}

export default function ExpirationBanner({
  variant,
  daysRemaining,
  expirationDate,
  daysUntilDeletion,
}: ExpirationBannerProps) {
  const isExpired = variant === "error";

  let title: string;
  let subtitle: string;

  if (isExpired) {
    title = daysUntilDeletion
      ? `Your subscription has expired. Data will be deleted in ${daysUntilDeletion} days.`
      : "Your subscription has expired.";
    subtitle = expirationDate
      ? `Renew your subscription by ${expirationDate} to restore access.`
      : "Renew your subscription to restore access to paid features.";
  } else {
    title = `Your subscription is expiring in ${daysRemaining} days.`;
    subtitle = `Renew your subscription by ${expirationDate} to avoid disruption.`;
  }

  return (
    <Message
      static
      info={variant === "info"}
      warning={variant === "warning"}
      error={variant === "error"}
      text={title}
      description={subtitle}
      close={false}
      className="w-full"
    />
  );
}
