"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { markdown } from "@opal/utils";
import { Section } from "@/layouts/general-layouts";
import { Content, InputErrorText, InputVertical, toast } from "@opal/layouts";
import Card from "@/refresh-components/cards/Card";
import { Button, MessageCard } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import InfoBlock from "@/refresh-components/messages/InfoBlock";
import InputNumber from "@/refresh-components/inputs/InputNumber";
import {
  SvgUsers,
  SvgExternalLink,
  SvgArrowRight,
  SvgPlus,
  SvgWallet,
  SvgFileText,
  SvgOrganization,
} from "@opal/icons";
import {
  BillingInformation,
  BillingStatus,
  LicenseStatus,
  PaymentMethodRequiredError,
  StripePortalFlowType,
} from "@/lib/billing/interfaces";
import {
  createCustomerPortalSession,
  endTrial,
  resetStripeConnection,
  updateSeatCount,
  claimLicense,
} from "@/lib/billing/svc";
import { formatDateShort } from "@/lib/dateUtils";
import { humanReadableFormatShort } from "@opal/time";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/settings/types";
import useUsers from "@/hooks/useUsers";

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

const GRACE_PERIOD_DAYS = 30;
const MS_PER_DAY = 86_400_000;

/** How many days of a trial are left. Rounds up so a partial day still counts
 *  as a whole day; the caller reads a non-positive result as "today". */
function trialDaysRemaining(trialEnd: Date, now: number = Date.now()): number {
  return Math.ceil((trialEnd.getTime() - now) / MS_PER_DAY);
}

// ----------------------------------------------------------------------------
// Helpers
// ----------------------------------------------------------------------------

function getExpirationState(
  billing: BillingInformation,
  license?: LicenseStatus
) {
  const isAnnualBilling = billing.billing_period === "annual";

  // Check license expiration for self-hosted
  if (license?.expires_at) {
    const expiresAt = new Date(license.expires_at);
    const now = new Date();
    const daysRemaining = Math.ceil(
      (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (daysRemaining <= 0 || license.status === "expired") {
      const gracePeriodEnd = license.grace_period_end
        ? new Date(license.grace_period_end)
        : new Date(
            expiresAt.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000
          );
      const daysUntilDeletion = Math.max(
        0,
        Math.ceil(
          (gracePeriodEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
        )
      );
      return {
        variant: "error" as const,
        daysRemaining: 0,
        daysUntilDeletion,
        expirationDate: humanReadableFormatShort(gracePeriodEnd),
      };
    }

    // Only show warning for annual subscriptions (30 days before expiration)
    if (isAnnualBilling && daysRemaining <= 30) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }
  }

  // Check billing expiration for cloud (only show warnings for canceled subscriptions)
  if (billing.cancel_at_period_end && billing.current_period_end) {
    const expiresAt = new Date(billing.current_period_end);
    const now = new Date();
    const daysRemaining = Math.ceil(
      (expiresAt.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
    );

    if (daysRemaining <= 0) {
      const gracePeriodEnd = new Date(
        expiresAt.getTime() + GRACE_PERIOD_DAYS * 24 * 60 * 60 * 1000
      );
      const daysUntilDeletion = Math.max(
        0,
        Math.ceil(
          (gracePeriodEnd.getTime() - now.getTime()) / (1000 * 60 * 60 * 24)
        )
      );
      return {
        variant: "error" as const,
        daysRemaining: 0,
        daysUntilDeletion,
        expirationDate: humanReadableFormatShort(gracePeriodEnd),
      };
    }

    // Only show warning for annual subscriptions (30 days before expiration)
    // Monthly subscriptions auto-renew, so no warning needed
    if (isAnnualBilling && daysRemaining <= 30) {
      return {
        variant: "warning" as const,
        daysRemaining,
        expirationDate: humanReadableFormatShort(expiresAt),
      };
    }
  }

  if (billing.status === "expired" || billing.status === "cancelled") {
    return {
      variant: "error" as const,
      daysRemaining: 0,
      daysUntilDeletion: GRACE_PERIOD_DAYS,
      expirationDate: "",
    };
  }

  return null;
}

// ----------------------------------------------------------------------------
// SubscriptionCard
// ----------------------------------------------------------------------------

function SubscriptionCard({
  billing,
  license,
  onViewPlans,
  disabled,
  isManualLicenseOnly,
  onReconnect,
  onRefresh,
}: {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  disabled?: boolean;
  isManualLicenseOnly?: boolean;
  onReconnect?: () => Promise<void>;
  onRefresh?: () => Promise<void>;
}) {
  const t = useTranslations("admin.billing");
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isEndingTrial, setIsEndingTrial] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);

  const settings = useSettings();
  const tier = settings.tier;
  const isEnterprise = tier === Tier.ENTERPRISE || tier == null;
  const planName = isEnterprise
    ? t("subscription.enterprisePlan.name")
    : t("subscription.businessPlan.name");
  const PlanIcon = isEnterprise ? SvgOrganization : SvgUsers;
  const expirationDate = billing?.current_period_end ?? license?.expires_at;
  const formattedDate = formatDateShort(expirationDate);

  const isExpiredFromBilling =
    billing?.status === "expired" || billing?.status === "cancelled";
  const isExpiredFromLicense =
    license?.status === "expired" ||
    license?.status === "gated_access" ||
    (license?.expires_at && new Date(license.expires_at) < new Date());
  const isExpired = isExpiredFromBilling || isExpiredFromLicense;
  const isCanceling = billing?.cancel_at_period_end;
  // The license is the entitlement, so a Stripe snapshot that disagrees with it
  // would describe a trial this instance is not actually on.
  const trialEnd = license?.trial_end ? new Date(license.trial_end) : null;
  const isOnTrial = trialEnd !== null && trialEnd.getTime() > Date.now();
  let subtitle: string;
  if (isExpired) {
    subtitle = t("subscription.expired.subtitle", { date: formattedDate });
  } else if (isCanceling) {
    subtitle = t("subscription.validUntil.subtitle", { date: formattedDate });
  } else if (isOnTrial) {
    // The trial ending and the first charge are one event, so both halves of
    // this line have to come from the same date.
    const trialDate = formatDateShort(license?.trial_end);
    const daysLeft = trialDaysRemaining(trialEnd);
    subtitle =
      daysLeft <= 0
        ? t("subscription.trialToday.subtitle", { date: trialDate })
        : daysLeft === 1
          ? t("subscription.trialTomorrow.subtitle", { date: trialDate })
          : t("subscription.trialDays.subtitle", {
              days: daysLeft,
              date: trialDate,
            });
  } else if (billing) {
    subtitle = t("subscription.nextPayment.subtitle", { date: formattedDate });
  } else {
    subtitle = t("subscription.validUntil.subtitle", { date: formattedDate });
  }

  const handleManagePlan = async () => {
    try {
      const response = await createCustomerPortalSession({
        return_url: `${window.location.origin}/admin/billing?portal_return=true`,
      });
      if (response.stripe_customer_portal_url) {
        window.location.href = response.stripe_customer_portal_url;
      }
    } catch (error) {
      console.error("Failed to open customer portal:", error);
    }
  };

  const handleReconnect = async () => {
    setIsReconnecting(true);
    try {
      await resetStripeConnection();
      await onReconnect?.();
    } catch (error) {
      console.error("Failed to reconnect to Stripe:", error);
    } finally {
      setIsReconnecting(false);
    }
  };

  const handleSyncLicense = async () => {
    setIsSyncing(true);
    try {
      await claimLicense();
      await onRefresh?.();
    } catch (error) {
      toast.error(
        error instanceof Error ? error.message : t("toasts.syncLicenseFailed")
      );
    } finally {
      setIsSyncing(false);
    }
  };

  const handleEndTrial = async () => {
    setIsEndingTrial(true);
    try {
      await endTrial();
      await onRefresh?.();
    } catch (error) {
      if (error instanceof PaymentMethodRequiredError) {
        // Deep-link the user to the Stripe add-payment-method screen, then
        // return to /admin/billing with a marker that auto-retries the
        // upgrade so they don't have to click the button again.
        try {
          const response = await createCustomerPortalSession({
            return_url: `${window.location.origin}/admin/billing?portal_return=true&retry_upgrade=1`,
            flow_type: StripePortalFlowType.PAYMENT_METHOD_UPDATE,
          });
          if (response.stripe_customer_portal_url) {
            window.location.href = response.stripe_customer_portal_url;
            return;
          }
        } catch (portalError) {
          console.error("Failed to open customer portal:", portalError);
          toast.error(t("toasts.paymentMethodRequired"));
        }
      } else {
        toast.error(
          error instanceof Error ? error.message : t("toasts.endTrialFailed")
        );
      }
    } finally {
      setIsEndingTrial(false);
    }
  };

  // Only cloud exposes ending a trial early. Self-hosted has no such control.
  const canEndTrialEarly =
    NEXT_PUBLIC_CLOUD_ENABLED && billing?.status === BillingStatus.TRIALING;

  return (
    <Card>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        height="auto"
      >
        <Section gap={1} alignItems="start" height="auto" width="auto">
          <PlanIcon className="w-5 h-5" />
          <Text headingH3Muted text04>
            {planName}
          </Text>
          <Text secondaryBody text03>
            {subtitle}
          </Text>
        </Section>
        <Section
          flexDirection="column"
          gap={1}
          alignItems="end"
          height="auto"
          width="fit"
        >
          {isManualLicenseOnly ? (
            <Text secondaryBody text03 className="text-right">
              {t.rich("subscription.managedBySales.text", {
                br: () => <br />,
                link: (chunks) => (
                  <a
                    href="mailto:support@onyx.app?subject=Billing%20change%20request"
                    className="underline"
                  >
                    {chunks}
                  </a>
                ),
              })}
            </Text>
          ) : disabled ? (
            <Button
              disabled={isReconnecting}
              prominence="secondary"
              onClick={handleReconnect}
              rightIcon={SvgArrowRight}
            >
              {isReconnecting
                ? t("subscription.connecting.label")
                : t("subscription.connectToStripe.label")}
            </Button>
          ) : (
            <Section
              flexDirection="row"
              gap={2}
              alignItems="end"
              height="auto"
              width="auto"
            >
              {canEndTrialEarly && (
                <Button
                  disabled={isEndingTrial}
                  onClick={handleEndTrial}
                  rightIcon={SvgArrowRight}
                >
                  {isEndingTrial
                    ? t("subscription.upgrading.label")
                    : t("subscription.upgradeNow.label")}
                </Button>
              )}
              {/* Cloud has no local license to pull. Self-hosted refreshes
                  itself only inside LICENSE_RECLAIM_WINDOW, so a change made
                  earlier in the period needs a manual pull. */}
              {!NEXT_PUBLIC_CLOUD_ENABLED && (
                <Button
                  disabled={isSyncing}
                  prominence="secondary"
                  onClick={handleSyncLicense}
                >
                  {isSyncing
                    ? t("subscription.syncing.label")
                    : t("subscription.syncLicense.label")}
                </Button>
              )}
              <Button
                prominence={canEndTrialEarly ? "secondary" : "primary"}
                onClick={handleManagePlan}
                rightIcon={SvgExternalLink}
              >
                {t("subscription.managePlan.label")}
              </Button>
            </Section>
          )}
          <Button prominence="tertiary" onClick={onViewPlans}>
            {t("subscription.viewPlanDetails.label")}
          </Button>
        </Section>
      </Section>
    </Card>
  );
}

// ----------------------------------------------------------------------------
// SeatsCard
// ----------------------------------------------------------------------------

function SeatsCard({
  billing,
  license,
  onRefresh,
  disabled,
  hideUpdateSeats,
}: {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onRefresh?: () => Promise<void>;
  disabled?: boolean;
  hideUpdateSeats?: boolean;
}) {
  const t = useTranslations("admin.billing");
  const [isEditing, setIsEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const { data: usersData, isLoading: isLoadingUsers } = useUsers({
    includeApiKeys: false,
  });

  // Seat enforcement reads the license, so preferring the billing snapshot can
  // render a count the instance would refuse to honor. Seats default to 0
  // without a license, which is not a count to prefer over billing.
  const licensedSeats = license?.has_license ? license.seats : undefined;
  const totalSeats = licensedSeats ?? billing?.seats ?? 0;
  const acceptedUsers =
    usersData?.accepted?.filter((u) => u.is_active).length ?? 0;
  const slackUsers =
    usersData?.slack_users?.filter((u) => u.is_active).length ?? 0;
  const usedSeats = acceptedUsers + slackUsers;
  const pendingSeats = usersData?.invited?.length ?? 0;
  const remainingSeats = Math.max(0, totalSeats - usedSeats - pendingSeats);

  const [newSeatCount, setNewSeatCount] = useState(totalSeats);
  const minRequiredSeats = usedSeats + pendingSeats;
  const isBelowMinimum = newSeatCount < minRequiredSeats;

  const handleStartEdit = () => {
    setNewSeatCount(totalSeats);
    setError(null);
    setIsEditing(true);
  };

  const handleCancel = () => {
    setIsEditing(false);
    setError(null);
  };

  const handleConfirm = async () => {
    if (newSeatCount === totalSeats) {
      setIsEditing(false);
      return;
    }
    if (isBelowMinimum) return;

    setIsSubmitting(true);
    setError(null);

    try {
      await updateSeatCount({ new_seat_count: newSeatCount });
      if (!NEXT_PUBLIC_CLOUD_ENABLED) {
        // Wait for control plane to process the subscription update before claiming
        await new Promise((resolve) => setTimeout(resolve, 1500));
        await claimLicense();
      }
      await onRefresh?.();
      setIsEditing(false);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : t("seats.updateFailed.error")
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  const seatDifference = newSeatCount - totalSeats;
  const isAdding = seatDifference > 0;
  const isRemoving = seatDifference < 0;
  const nextBillingDate = formatDateShort(billing?.current_period_end);
  const seatCount = Math.abs(seatDifference);

  if (isEditing) {
    return (
      <Card
        padding={0}
        gap={0}
        alignItems="stretch"
        className="billing-card-enter"
      >
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          padding={4}
          height="auto"
        >
          <Content
            title={t("seats.updateSeats.title")}
            description={t("seats.updateSeats.description")}
            sizePreset="main-content"
            variant="section"
          />
          <Button
            disabled={isSubmitting}
            prominence="secondary"
            onClick={handleCancel}
          >
            {t("seats.cancel.label")}
          </Button>
        </Section>

        <div className="billing-content-area">
          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={1}
            padding={4}
            height="auto"
          >
            <InputVertical title={t("seats.seatsField.title")} withLabel>
              <InputNumber
                value={newSeatCount}
                onChange={(v) => setNewSeatCount(v ?? 1)}
                min={1}
                defaultValue={totalSeats}
                showReset
                variant={isBelowMinimum ? "error" : "primary"}
              />
            </InputVertical>

            {isBelowMinimum ? (
              <InputErrorText type="error">
                {markdown(
                  t("seats.belowMinimum.error", { minimum: minRequiredSeats })
                )}
              </InputErrorText>
            ) : seatDifference !== 0 ? (
              <Text secondaryBody text03>
                {isAdding
                  ? t("seats.delta.added", { count: seatCount })
                  : t("seats.delta.removed", { count: seatCount })}
              </Text>
            ) : null}

            {error && (
              <Text secondaryBody className="billing-error-text">
                {error}
              </Text>
            )}
          </Section>
        </div>

        <Section
          flexDirection="row"
          alignItems="center"
          justifyContent="between"
          padding={4}
          height="auto"
        >
          {isAdding ? (
            <Text secondaryBody text03>
              {t.rich("seats.billing.added", {
                count: seatCount,
                value: (chunks) => (
                  <Text secondaryBody text04>
                    {chunks}
                  </Text>
                ),
              })}
            </Text>
          ) : isRemoving ? (
            <Text secondaryBody text03>
              {t.rich("seats.billing.removed", {
                count: seatCount,
                date: nextBillingDate,
                value: (chunks) => (
                  <Text secondaryBody text04>
                    {chunks}
                  </Text>
                ),
              })}
            </Text>
          ) : (
            <Text secondaryBody text03>
              {t("seats.billing.unchanged")}
            </Text>
          )}
          <Button
            disabled={
              isSubmitting || newSeatCount === totalSeats || isBelowMinimum
            }
            onClick={handleConfirm}
          >
            {isSubmitting
              ? t("seats.saving.label")
              : t("seats.confirmChange.label")}
          </Button>
        </Section>
      </Card>
    );
  }

  return (
    <Card>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="center"
        height="auto"
      >
        <Section gap={1} alignItems="start" height="auto" width="auto">
          <Text mainContentMuted text04>
            {t("seats.total.label", { count: totalSeats })}
          </Text>
          <Text secondaryBody text03>
            {t("seats.breakdown.label", {
              used: usedSeats,
              pending: pendingSeats,
              remaining: remainingSeats,
            })}
          </Text>
        </Section>
        <Section
          flexDirection="row"
          gap={2}
          justifyContent="end"
          height="auto"
          width="auto"
        >
          <Button
            prominence="tertiary"
            href="/admin/users"
            icon={SvgExternalLink}
          >
            {t("seats.viewUsers.label")}
          </Button>
          {!hideUpdateSeats && (
            <Button
              disabled={isLoadingUsers || disabled || !billing}
              prominence="secondary"
              onClick={handleStartEdit}
              icon={SvgPlus}
            >
              {t("seats.updateSeats.label")}
            </Button>
          )}
        </Section>
      </Section>
    </Card>
  );
}

// ----------------------------------------------------------------------------
// PaymentSection
// ----------------------------------------------------------------------------

function PaymentSection({ billing }: { billing: BillingInformation }) {
  const t = useTranslations("admin.billing");
  const handleOpenPortal = async () => {
    try {
      const response = await createCustomerPortalSession({
        return_url: `${window.location.origin}/admin/billing?portal_return=true`,
      });
      if (response.stripe_customer_portal_url) {
        window.location.href = response.stripe_customer_portal_url;
      }
    } catch (error) {
      console.error("Failed to open customer portal:", error);
    }
  };

  if (!billing.payment_method_enabled) return null;

  const lastPaymentDate = formatDateShort(billing.current_period_start);

  return (
    <div className="billing-payment-section">
      <Section alignItems="start" height="auto" width="full">
        <Text mainContentEmphasis>{t("payment.section.title")}</Text>
        <Section flexDirection="row" gap={2} alignItems="stretch" height="auto">
          <Card className="billing-payment-card">
            <Section
              flexDirection="row"
              justifyContent="between"
              alignItems="start"
              height="auto"
            >
              <InfoBlock
                icon={SvgWallet}
                title={t("payment.card.title")}
                description={t("payment.card.description")}
              />
              <Button
                prominence="tertiary"
                onClick={handleOpenPortal}
                rightIcon={SvgExternalLink}
              >
                {t("payment.update.label")}
              </Button>
            </Section>
          </Card>
          {lastPaymentDate && (
            <Card className="billing-payment-card">
              <Section
                flexDirection="row"
                justifyContent="between"
                alignItems="start"
                height="auto"
              >
                <InfoBlock
                  icon={SvgFileText}
                  title={lastPaymentDate}
                  description={t("payment.lastPayment.description")}
                />
                <Button
                  prominence="tertiary"
                  onClick={handleOpenPortal}
                  rightIcon={SvgExternalLink}
                >
                  {t("payment.viewInvoice.label")}
                </Button>
              </Section>
            </Card>
          )}
        </Section>
      </Section>
    </div>
  );
}

// ----------------------------------------------------------------------------
// BillingDetailsView
// ----------------------------------------------------------------------------

interface BillingDetailsViewProps {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  onRefresh?: () => Promise<void>;
  isAirGapped?: boolean;
  isManualLicenseOnly?: boolean;
  hasStripeError?: boolean;
  licenseCard?: React.ReactNode;
  isGraceSyncing?: boolean;
}

export default function BillingDetailsView({
  billing,
  license,
  onViewPlans,
  onRefresh,
  isAirGapped,
  isManualLicenseOnly,
  hasStripeError,
  licenseCard,
  isGraceSyncing,
}: BillingDetailsViewProps) {
  const t = useTranslations("admin.billing");
  const expirationState = billing ? getExpirationState(billing, license) : null;
  const disableBillingActions =
    isAirGapped || hasStripeError || isManualLicenseOnly;

  return (
    <Section gap={4} height="auto" width="full">
      {/* Renewal fetched on arrival while expired. The page renders regardless:
          billing is the one route a lapsed instance must always reach. */}
      {isGraceSyncing && (
        <MessageCard variant="info" title={t("banners.graceSync.title")} />
      )}
      {/* Stripe connection error banner */}
      {hasStripeError && (
        <MessageCard
          variant="warning"
          title={t("banners.stripeError.title")}
          description={t("banners.stripeError.description")}
        />
      )}

      {/* Air-gapped mode info banner */}
      {isAirGapped && !hasStripeError && !isManualLicenseOnly && (
        <MessageCard
          variant="info"
          title={t("banners.airGapped.title")}
          description={t("banners.airGapped.description")}
        />
      )}

      {/* Expiration banner */}
      {expirationState && (
        <MessageCard
          variant={expirationState.variant}
          title={
            expirationState.variant === "error"
              ? expirationState.daysUntilDeletion
                ? t("banners.expired.withDeletion.title", {
                    days: expirationState.daysUntilDeletion,
                  })
                : t("banners.expired.title")
              : t("banners.expiring.title", {
                  days: expirationState.daysRemaining,
                })
          }
          description={
            expirationState.variant === "error"
              ? expirationState.expirationDate
                ? t("banners.expired.withDate.description", {
                    date: expirationState.expirationDate,
                  })
                : t("banners.expired.description")
              : t("banners.expiring.description", {
                  date: expirationState.expirationDate,
                })
          }
        />
      )}

      {/* Subscription card */}
      {(billing || license?.has_license) && (
        <SubscriptionCard
          billing={billing}
          license={license}
          onViewPlans={onViewPlans}
          disabled={disableBillingActions}
          isManualLicenseOnly={isManualLicenseOnly}
          onReconnect={onRefresh}
          onRefresh={onRefresh}
        />
      )}

      {/* License card (inline for manual license users) */}
      {licenseCard}

      {/* Seats card */}
      <SeatsCard
        billing={billing}
        license={license}
        onRefresh={onRefresh}
        disabled={disableBillingActions}
        hideUpdateSeats={isManualLicenseOnly}
      />

      {/* Payment section */}
      {/* TODO: Re-enable payment section when APIs for fetching payment details are implemented */}
      {/* {billing?.payment_method_enabled && !isAirGapped && <PaymentSection billing={billing} />} */}
    </Section>
  );
}
