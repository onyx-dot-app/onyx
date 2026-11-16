"use client";

import { NavLink, useNavigation } from "@opal/navigation";
import { useState } from "react";
import { useTranslations } from "next-intl";
import ErrorPageLayout from "@/components/errorPages/ErrorPageLayout";
import { Button, Text, useCreateModal } from "@opal/components";
import DowngradeToCommunityModal from "@/sections/modals/DowngradeToCommunityModal";
import { useUser } from "@/providers/UserProvider";
import { logout } from "@/lib/users/svc";
import { loginPath } from "@/lib/auth/paths";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useLicense } from "@/hooks/useLicense";
import { useSettings } from "@/lib/settings/hooks";
import { ApplicationStatus } from "@/lib/settings/types";
import { richNodes } from "@opal/utils";
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
  const { appName } = settings;
  const { isAdmin } = useUser();
  const downgradeModal = useCreateModal();
  const navigation = useNavigation();

  // Lands on the held login page: with SSO as the only way in, a reload would
  // sign the user straight back in through the IdP session.
  async function handleLogout() {
    await logout();
    navigation.load(loginPath({ autoRedirectToSso: false }));
  }

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
        ? t("accessRestricted.subscriptionLapse.description", { appName })
        : t("accessRestricted.licenseLapse.description", { appName })
      : t("accessRestricted.licenseRequired.description", { appName });

  const handleResubscribe = async () => {
    setIsLoading(true);
    setError(null);
    try {
      // `url` covers both the new-checkout and past_due payment-update responses.
      const { url } = await fetchResubscriptionSession();
      if (!url) {
        throw new Error("No redirect URL returned");
      }
      navigation.load(url);
    } catch (error) {
      console.error("Error creating resubscription session:", error);
      setError(t("accessRestricted.resubscribeError.text"));
      setIsLoading(false);
    }
  };

  return (
    <ErrorPageLayout>
      <div className="flex items-center gap-2">
        <Text font="heading-headline" color="text-05">
          {t("accessRestricted.heading.title")}
        </Text>
        <SvgLock className="stroke-status-error-05 w-6 h-6" />
      </div>

      <Text color="text-03">{initialModalMessage}</Text>

      {isSeatLimitExceeded ? (
        <>
          <Text color="text-03">
            {richNodes(
              t.rich("accessRestricted.seatLimitAdminHint.text", {
                userLink: (chunks) => (
                  <NavLink className={linkClassName} href="/admin/users">
                    {chunks}
                  </NavLink>
                ),
                billingLink: (chunks) => (
                  <NavLink className={linkClassName} href="/admin/billing">
                    {chunks}
                  </NavLink>
                ),
              })
            )}
          </Text>

          <div className="flex flex-row gap-2">
            <Button onClick={handleLogout}>
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>
        </>
      ) : NEXT_PUBLIC_CLOUD_ENABLED ? (
        <>
          <Text color="text-03">
            {t("accessRestricted.updatePayment.description", { appName })}
          </Text>

          <Text color="text-03">
            {t("accessRestricted.manageSubscription.description")}
          </Text>

          <div className="flex flex-row gap-2">
            <Button disabled={isLoading} onClick={handleResubscribe}>
              {isLoading
                ? t("accessRestricted.resubscribeButton.loading")
                : t("accessRestricted.resubscribeButton.label")}
            </Button>
            <Button prominence="secondary" onClick={handleLogout}>
              {t("accessRestricted.logoutButton.label")}
            </Button>
          </div>

          {error && <Text color="status-error-05">{error}</Text>}
        </>
      ) : (
        <>
          <Text color="text-03">
            {hadPreviousLicense
              ? t("accessRestricted.renewLicense.description", { appName })
              : t("accessRestricted.obtainLicense.description")}
          </Text>

          <Text color="text-03">
            {richNodes(
              t.rich("accessRestricted.billingAdminHint.text", {
                hadLicense: hadPreviousLicense ? "true" : "false",
                billingLink: (chunks) => (
                  <NavLink className={linkClassName} href="/admin/billing">
                    {chunks}
                  </NavLink>
                ),
                supportLink: (chunks) => (
                  <a className={linkClassName} href="mailto:support@onyx.app">
                    {chunks}
                  </a>
                ),
              })
            )}
          </Text>

          <div className="flex flex-row gap-2">
            <Button onClick={handleLogout}>
              {t("accessRestricted.logoutButton.label")}
            </Button>
            {isAdmin && (
              <Button
                prominence="secondary"
                onClick={() => downgradeModal.toggle(true)}
              >
                {t("accessRestricted.downgradeButton.label")}
              </Button>
            )}
          </div>

          {downgradeModal.isOpen && (
            <DowngradeToCommunityModal
              onClose={() => downgradeModal.toggle(false)}
            />
          )}
        </>
      )}

      <Text color="text-03">
        {richNodes(
          t.rich("needHelp.text", {
            discordLink: (chunks) => (
              <a
                className={linkClassName}
                href="https://discord.gg/4NA5SbzrWb"
                target="_blank"
                rel="noopener noreferrer"
              >
                {chunks}
              </a>
            ),
          })
        )}
      </Text>
    </ErrorPageLayout>
  );
}
