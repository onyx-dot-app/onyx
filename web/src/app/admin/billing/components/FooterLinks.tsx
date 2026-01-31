"use client";

import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import Button from "@/refresh-components/buttons/Button";
import { useUser } from "@/components/user/UserProvider";

const SUPPORT_EMAIL = "support@onyx.app";

interface FooterLinksProps {
  hasSubscription?: boolean;
  onActivateLicense?: () => void;
  /** Hide the license activation link (when card is already open) */
  hideLicenseLink?: boolean;
}

export default function FooterLinks({
  hasSubscription,
  onActivateLicense,
  hideLicenseLink,
}: FooterLinksProps) {
  const { user } = useUser();

  const licenseText = hasSubscription
    ? "Update License Key"
    : "Activate License Key";

  const billingHelpHref = `mailto:${SUPPORT_EMAIL}?subject=${encodeURIComponent(
    `[Billing] support for ${user?.email ?? "unknown"}`
  )}`;

  return (
    <Section flexDirection="row" justifyContent="center" gap={1} height="auto">
      {onActivateLicense && !hideLicenseLink && (
        <>
          <Text secondaryBody text03>
            Have a license key?
          </Text>
          <Button action tertiary onClick={onActivateLicense}>
            <Text secondaryBody text03 underline>
              {licenseText}
            </Text>
          </Button>
        </>
      )}
      <Button
        action
        tertiary
        href={billingHelpHref}
        className="billing-text-link"
      >
        <Text secondaryBody text03 underline>
          Billing Help
        </Text>
      </Button>
    </Section>
  );
}
