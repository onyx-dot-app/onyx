"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { Button } from "@opal/components";
import InlineExternalLink from "@/refresh-components/InlineExternalLink";
import { logout } from "@/lib/users/svc";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useLicense } from "@/hooks/useLicense";
import { useSettings } from "@/lib/settings/hooks";
import { ApplicationStatus } from "@/lib/settings/types";
import Text from "@/refresh-components/texts/Text";
import { SvgLock } from "@opal/icons";

const linkClassName =
  "text-action-selection-05 hover:text-action-selection-06 underline";

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
  const t = useTranslations("common.errorPages");
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
    return used_seats != null && seat_count != null
      ? t("accessRestricted.seatLimitWithCounts.description", {
          used: used_seats,
          seats: seat_count,
        })
      : t("accessRestricted.seatLimit.description");
  }

  const initialModalMessage = isSeatLimitExceeded
    ? getSeatLimitMessage()
    : showRenewalMessage
      ? NEXT_PUBLIC_CLOUD_ENABLED
        ? t("accessRestricted.subscriptionLapse.description")
        : t("accessRestricted.licenseLapse.description")
      : t("accessRestricted.licenseRequired.description");

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
      setError(t("accessRestricted.resubscribeError.text"));
      setIsLoading(false);
    }
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text headingH2>{t("accessRestricted.heading.title")}</Text>
        <SvgLock className="stroke-status-error-05 w-6 h-6" />
      </div>

      <Text text03>{initialModalMessage}</Text>

      {isSeatLimitExceeded ? (
        <>
          <Text text03>
            {t.rich("accessRestricted.seatLimitAdminHint.text", {
              userLink: (chunks) => (
                <Link className={linkClassName} href="/admin/users">
                  {chunks}
                </Link>
              ),
              billingLink: (chunks) => (
                <Link className={linkClassName} href="/admin/billing">
                  {chunks}
                </Link>
              ),
            })}
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>
        </>
      ) : NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text text03>{t("accessRestricted.updatePayment.description")}</Text>

          <Text text03>
            {t("accessRestricted.manageSubscription.description")}
          </Text>

          <div className="flex flex-row gap-2">
            <Button disabled={isLoading} onClick={handleResubscribe}>
              {isLoading
                ? t("accessRestricted.resubscribeButton.loading")
                : t("accessRestricted.resubscribeButton.label")}
            </Button>
            <Button
              prominence="secondary"
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>

          {error && <Text className="text-status-error-05">{error}</Text>}
        </>
      ) : (
        <>
          <Text text03>
            {hadPreviousLicense
              ? t("accessRestricted.renewLicense.description")
              : t("accessRestricted.obtainLicense.description")}
          </Text>

          <Text text03>
            {t.rich("accessRestricted.billingAdminHint.text", {
              hadLicense: hadPreviousLicense ? "true" : "false",
              billingLink: (chunks) => (
                <Link className={linkClassName} href="/admin/billing">
                  {chunks}
                </Link>
              ),
              supportLink: (chunks) => (
                <a className={linkClassName} href="mailto:support@onyx.app">
                  {chunks}
                </a>
              ),
            })}
          </Text>

          <div className="flex flex-row gap-2">
            <Button
              onClick={async () => {
                await logout();
                window.location.reload();
              }}
            >
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>
        </>
      )}

      <Text text03>
        {t.rich("needHelp.text", {
          discordLink: (chunks) => (
            <InlineExternalLink
              className={linkClassName}
              href="https://discord.gg/4NA5SbzrWb"
            >
              {chunks}
            </InlineExternalLink>
          ),
        })}
      </Text>
    </ErrorPageLayout>
  );
}
