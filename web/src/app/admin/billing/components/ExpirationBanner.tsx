"use client";

import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { SvgAlertCircle, SvgAlertTriangle } from "@opal/icons";

type BannerVariant = "warning" | "error";

interface ExpirationBannerProps {
  variant: BannerVariant;
  daysRemaining?: number;
  expirationDate?: string;
}

export default function ExpirationBanner({
  variant,
  daysRemaining,
  expirationDate,
}: ExpirationBannerProps) {
  const isExpired = variant === "error";

  const Icon = isExpired ? SvgAlertTriangle : SvgAlertCircle;
  const iconColorClass = isExpired
    ? "stroke-status-error-05"
    : "stroke-status-warning-05";

  const title = isExpired
    ? "Your subscription has expired."
    : `Your subscription is expiring in ${daysRemaining} days.`;

  const subtitle = isExpired
    ? "Renew your subscription to restore access to paid features."
    : `Renew your subscription by ${expirationDate} to avoid disruption.`;

  return (
    <div className="billing-banner" data-variant={variant}>
      <Icon className={`w-5 h-5 flex-shrink-0 ${iconColorClass}`} />
      <Section gap={0.25} alignItems="start" height="auto">
        <Text mainContentEmphasis>{title}</Text>
        <Text secondaryBody text03>
          {subtitle}
        </Text>
      </Section>
    </div>
  );
}
