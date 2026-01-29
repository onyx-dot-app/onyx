"use client";

import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";

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
          <Button tertiary onClick={onActivateLicense}>
            <Text secondaryBody text03 underline>
              {licenseText}
            </Text>
          </Button>
        </>
      )}
      <Button
        action
        tertiary
        href={BILLING_HELP_URL}
        target="_blank"
        className="billing-text-link"
      >
        <Text secondaryBody text03 underline>
          Billing Help
        </Text>
      </Button>
    </Section>
  );
}
