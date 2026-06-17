"use client";

import { useState } from "react";
import Link from "next/link";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { Button } from "@opal/components";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { logout } from "@/lib/user";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useLicense } from "@/hooks/useLicense";
import { useSettings } from "@/lib/settings/hooks";
import { ApplicationStatus } from "@/lib/settings/types";
import Text from "@/refresh-components/texts/Text";
import { SvgLock } from "@opal/icons";

const linkClassName = "text-action-link-05 hover:text-action-link-06 underline";

interface ResubscriptionSessionResponse {
  sessionId: string | null;
  url: string | null;
  requires_payment_method_update: boolean;
}

const fetchResubscriptionSession =
  async (): Promise<ResubscriptionSessionResponse> => {
    const response = await fetch("/api/tenants/create-subscription-session", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
    });
    if (!response.ok) {
      throw new Error("Failed to create resubscription session");
    }
    return response.json();
  };

export default function AccessRestricted() {
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { data: license } = useLicense();
  const settings = useSettings();

  const isSeatLimitExceeded =
    settings.application_status === ApplicationStatus.SEAT_LIMIT_EXCEEDED;
  const hadPreviousLicense = license?.has_license === true;
  const showRenewalMessage = NEXT_PUBLIC_CLOUD_ENABLED || hadPreviousLicense;

  function getSeatLimitMessage() {
    const { used_seats, seat_count } = settings;
    const counts =
      used_seats != null && seat_count != null
        ? ` (${used_seats} users / ${seat_count} seats)`
        : "";
    return `Your organization has exceeded its licensed seat count${counts}. Access is restricted until the number of users is reduced or your license is upgraded.`;
  }

  const initialModalMessage = isSeatLimitExceeded
    ? getSeatLimitMessage()
    : showRenewalMessage
      ? NEXT_PUBLIC_CLOUD_ENABLED
        ? "Your access to Onyx has been temporarily suspended due to a lapse in your subscription."
        : "Your access to Onyx has been temporarily suspended due to a lapse in your license."
      : "An Enterprise license is required to use Onyx. Your data is protected and will be available once a license is activated.";

  const handleResubscribe = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // `url` covers both the new-checkout and past_due payment-update responses.
      const { url } = await fetchResubscriptionSession();
      if (!url) {
        throw new Error("No redirect URL returned");
      }
      window.location.href = url;
    } catch (error) {
      console.error("Error creating resubscription session:", error);
      setError("Error opening resubscription page. Please try again later.");
      setIsLoading(false);
    }
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text headingH2>Access Restricted</Text>
        <SvgLock className="stroke-status-error-05 w-6 h-6" />
      </div>

      <Text text03>{initialModalMessage}</Text>

      {isSeatLimitExceeded ? (
        <>
          <Text text03>
            If you are an administrator, you can manage users on the{" "}
            <Link className={linkClassName} href="/admin/users">
              User Management
            </Link>{" "}
            page or upgrade your license on the{" "}
            <Link className={linkClassName} href="/admin/billing">
              Admin Billing
            </Link>{" "}
            page.
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Log out
            </Button>
          </div>
        </>
      ) : NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text text03>
            To reinstate your access and continue benefiting from Onyx&apos;s
            powerful features, please update your payment information.
          </Text>

          <Text text03>
            If you&apos;re an admin, you can manage your subscription by
            clicking the button below. For other users, please reach out to your
            administrator to address this matter.
          </Text>

          <div className="flex flex-row gap-2">
            <Button disabled={isLoading} onClick={handleResubscribe}>
              {isLoading ? "Loading..." : "Resubscribe"}
            </Button>
            <Button
              prominence="secondary"
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Log out
            </Button>
          </div>

          {error && <Text className="text-status-error-05">{error}</Text>}
        </>
      ) : (
        <>
          <Text text03>
            {hadPreviousLicense
              ? "To reinstate your access and continue using Onyx, please contact your system administrator to renew your license."
              : "To get started, please contact your system administrator to obtain an Enterprise license."}
          </Text>

          <Text text03>
            If you are the administrator, please visit the{" "}
            <Link className={linkClassName} href="/admin/billing">
              Admin Billing
            </Link>{" "}
            page to {hadPreviousLicense ? "renew" : "activate"} your license,
            sign up through Stripe or reach out to{" "}
            <a className={linkClassName} href="mailto:support@onyx.app">
              support@onyx.app
            </a>{" "}
            for billing assistance.
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              Log out
            </Button>
          </div>
        </>
      )}

      <Text text03>
        Need help? Join our{" "}
        <InlineExternalLink
          className={linkClassName}
          href="https://discord.gg/4NA5SbzrWb"
        >
          Discord community
        </InlineExternalLink>{" "}
        for support.
      </Text>
    </ErrorPageLayout>
  );
}
