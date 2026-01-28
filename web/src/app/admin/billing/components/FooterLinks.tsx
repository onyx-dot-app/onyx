"use client";

import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";

const BILLING_HELP_URL = "https://docs.onyx.app/billing";

interface FooterLinksProps {
  hasSubscription?: boolean;
  onActivateLicense?: () => void;
}

export default function FooterLinks({
  hasSubscription,
  onActivateLicense,
}: FooterLinksProps) {
  const licenseText = hasSubscription
    ? "Update License Key"
    : "Activate License Key";

  return (
    <Section flexDirection="row" justifyContent="center" gap={1} height="auto">
      {onActivateLicense && (
        <>
          <Text secondaryBody text03>
            Have a license key?
          </Text>
          <button
            type="button"
            onClick={onActivateLicense}
            className="bg-transparent border-none cursor-pointer p-0 underline"
          >
            <Text secondaryBody text02>
              {licenseText}
            </Text>
          </button>
          <Text secondaryBody text03>
            |
          </Text>
        </>
      )}
      <a
        href={BILLING_HELP_URL}
        target="_blank"
        rel="noopener noreferrer"
        className="underline"
      >
        <Text secondaryBody text02>
          Billing Help
        </Text>
      </a>
    </Section>
  );
}
