"use client";

import { useState } from "react";
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

/** How much of a trial is left, in words. Rounds up so a partial day still
 *  reads as a day, and floors at "today" so a lagging status cannot go negative. */
function trialCountdown(trialEnd: Date, now: number = Date.now()): string {
  const days = Math.ceil((trialEnd.getTime() - now) / MS_PER_DAY);
  if (days <= 0) return "Trial ends today";
  if (days === 1) return "Trial ends tomorrow";
  return `Trial ends in ${days} days`;
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
  const [isReconnecting, setIsReconnecting] = useState(false);
  const [isEndingTrial, setIsEndingTrial] = useState(false);
  const [isSyncing, setIsSyncing] = useState(false);

  const settings = useSettings();
  const tier = settings.tier;
  const isEnterprise = tier === Tier.ENTERPRISE || tier == null;
  const planName = isEnterprise ? "Enterprise Plan" : "Business Plan";
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
    subtitle = `Expired on ${formattedDate}`;
  } else if (isCanceling) {
    subtitle = `Valid until ${formattedDate}`;
  } else if (isOnTrial) {
    // The trial ending and the first charge are one event, so both halves of
    // this line have to come from the same date.
    subtitle = `${trialCountdown(trialEnd)}. Payment required on ${formatDateShort(
      license?.trial_end
    )}`;
  } else if (billing) {
    subtitle = `Next payment on ${formattedDate}`;
  } else {
    subtitle = `Valid until ${formattedDate}`;
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
        error instanceof Error ? error.message : "Failed to sync license"
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
          toast.error("Add a payment method first, then try upgrading again.");
        }
      } else {
        toast.error(
          error instanceof Error ? error.message : "Failed to end trial"
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
              Your plan is managed through sales.
              <br />
              <a
                href="mailto:support@onyx.app?subject=Billing%20change%20request"
                className="underline"
              >
                Contact billing
              </a>{" "}
              to make changes.
            </Text>
          ) : disabled ? (
            <Button
              disabled={isReconnecting}
              prominence="secondary"
              onClick={handleReconnect}
              rightIcon={SvgArrowRight}
            >
              {isReconnecting ? "Connecting..." : "Connect to Stripe"}
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
                  {isEndingTrial ? "Upgrading..." : "Upgrade now"}
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
                  {isSyncing ? "Syncing..." : "Sync License"}
                </Button>
              )}
              <Button
                prominence={canEndTrialEarly ? "secondary" : "primary"}
                onClick={handleManagePlan}
                rightIcon={SvgExternalLink}
              >
                Manage Plan
              </Button>
            </Section>
          )}
          <Button prominence="tertiary" onClick={onViewPlans}>
            View Plan Details
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
      setError(err instanceof Error ? err.message : "Failed to update seats");
    } finally {
      setIsSubmitting(false);
    }
  };

  const seatDifference = newSeatCount - totalSeats;
  const isAdding = seatDifference > 0;
  const isRemoving = seatDifference < 0;
  const nextBillingDate = formatDateShort(billing?.current_period_end);
  const seatCount = Math.abs(seatDifference);
  const seatWord = seatCount === 1 ? "seat" : "seats";

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
            title="Update Seats"
            description="Add or remove seats to reflect your team size."
            sizePreset="main-content"
            variant="section"
          />
          <Button
            disabled={isSubmitting}
            prominence="secondary"
            onClick={handleCancel}
          >
            Cancel
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
            <InputVertical title="Seats" withLabel>
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
                  `You cannot set seats below current **${minRequiredSeats}** seats in use/pending. [Remove users](/admin/users) first before adjusting seats.`
                )}
              </InputErrorText>
            ) : seatDifference !== 0 ? (
              <Text secondaryBody text03>
                {Math.abs(seatDifference)} seat
                {Math.abs(seatDifference) !== 1 ? "s" : ""} to be{" "}
                {isAdding ? "added" : "removed"}
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
              You will be billed for the{" "}
              <Text secondaryBody text04>
                {seatCount}
              </Text>{" "}
              additional {seatWord} at a pro-rated amount.
            </Text>
          ) : isRemoving ? (
            <Text secondaryBody text03>
              <Text secondaryBody text04>
                {seatCount}
              </Text>{" "}
              {seatWord} will be removed on{" "}
              <Text secondaryBody text04>
                {nextBillingDate}
              </Text>{" "}
              (after current billing cycle).
            </Text>
          ) : (
            <Text secondaryBody text03>
              No changes to your billing.
            </Text>
          )}
          <Button
            disabled={
              isSubmitting || newSeatCount === totalSeats || isBelowMinimum
            }
            onClick={handleConfirm}
          >
            {isSubmitting ? "Saving..." : "Confirm Change"}
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
            {totalSeats} Seats
          </Text>
          <Text secondaryBody text03>
            {usedSeats} in use • {pendingSeats} pending • {remainingSeats}{" "}
            remaining
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
            View Users
          </Button>
          {!hideUpdateSeats && (
            <Button
              disabled={isLoadingUsers || disabled || !billing}
              prominence="secondary"
              onClick={handleStartEdit}
              icon={SvgPlus}
            >
              Update Seats
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
        <Text mainContentEmphasis>Payment</Text>
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
                title="Visa ending in 1234"
                description="Payment method"
              />
              <Button
                prominence="tertiary"
                onClick={handleOpenPortal}
                rightIcon={SvgExternalLink}
              >
                Update
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
                  description="Last payment"
                />
                <Button
                  prominence="tertiary"
                  onClick={handleOpenPortal}
                  rightIcon={SvgExternalLink}
                >
                  View Invoice
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
  const expirationState = billing ? getExpirationState(billing, license) : null;
  const disableBillingActions =
    isAirGapped || hasStripeError || isManualLicenseOnly;

  return (
    <Section gap={4} height="auto" width="full">
      {/* Renewal fetched on arrival while expired. The page renders regardless:
          billing is the one route a lapsed instance must always reach. */}
      {isGraceSyncing && (
        <MessageCard variant="info" title="Checking for a renewed license…" />
      )}
      {/* Stripe connection error banner */}
      {hasStripeError && (
        <MessageCard
          variant="warning"
          title="Unable to connect to Stripe payment portal."
          description="Check your internet connection or manually provide a license."
        />
      )}

      {/* Air-gapped mode info banner */}
      {isAirGapped && !hasStripeError && !isManualLicenseOnly && (
        <MessageCard
          variant="info"
          title="Air-gapped deployment"
          description="Online billing management is disabled. Contact support to update your subscription."
        />
      )}

      {/* Expiration banner */}
      {expirationState && (
        <MessageCard
          variant={expirationState.variant}
          title={
            expirationState.variant === "error"
              ? expirationState.daysUntilDeletion
                ? `Your subscription has expired. Data will be deleted in ${expirationState.daysUntilDeletion} days.`
                : "Your subscription has expired."
              : `Your subscription is expiring in ${expirationState.daysRemaining} days.`
          }
          description={
            expirationState.variant === "error"
              ? expirationState.expirationDate
                ? `Renew your subscription by ${expirationState.expirationDate} to restore access.`
                : "Renew your subscription to restore access to paid features."
              : `Renew your subscription by ${expirationState.expirationDate} to avoid disruption.`
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
