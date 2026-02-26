"use client";

import { useState } from "react";
import Link from "next/link";
import { Section, LineItemLayout } from "@/layouts/general-layouts";
import * as InputLayouts from "@/layouts/input-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import Message from "@/refresh-components/messages/Message";
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
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import {
  createCustomerPortalSession,
  resetStripeConnection,
  updateSeatCount,
  claimLicense,
  refreshLicenseCache,
} from "@/lib/billing/svc";
import { formatDateShort } from "@/lib/dateUtils";
import { humanReadableFormatShort } from "@/lib/time";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import useUsers from "@/hooks/useUsers";

// ----------------------------------------------------------------------------
// Constants
// ----------------------------------------------------------------------------

const GRACE_PERIOD_DAYS = 30;

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
}: {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onViewPlans: () => void;
  disabled?: boolean;
  isManualLicenseOnly?: boolean;
  onReconnect?: () => Promise<void>;
}) {
  const [isReconnecting, setIsReconnecting] = useState(false);

  const planName = isManualLicenseOnly ? "Enterprise Plan" : "Business Plan";
  const PlanIcon = isManualLicenseOnly ? SvgOrganization : SvgUsers;
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

  let subtitle: string;
  if (isExpired) {
    subtitle = `Expired on ${formattedDate}`;
  } else if (isCanceling) {
    subtitle = `Valid until ${formattedDate}`;
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

  return (
    <Card>
      <Section
        flexDirection="row"
        justifyContent="between"
        alignItems="start"
        height="auto"
      >
        <Section gap={0.25} alignItems="start" height="auto" width="auto">
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
          gap={0.25}
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
              main
              secondary
              onClick={handleReconnect}
              rightIcon={SvgArrowRight}
              disabled={isReconnecting}
            >
              {isReconnecting ? "Connecting..." : "Connect to Stripe"}
            </Button>
          ) : (
            <Button
              main
              primary
              onClick={handleManagePlan}
              rightIcon={SvgExternalLink}
            >
              Manage Plan
            </Button>
          )}
          <Button tertiary onClick={onViewPlans} className="billing-text-link">
            <Text secondaryBody text03>
              View Plan Details
            </Text>
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

  const totalSeats = billing?.seats ?? license?.seats ?? 0;
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
        // Force refresh the Redis cache from the database
        await refreshLicenseCache();
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
          padding={1}
          height="auto"
        >
          <LineItemLayout
            title="Update Seats"
            description="Add or remove seats to reflect your team size."
          />
          <Button main secondary onClick={handleCancel} disabled={isSubmitting}>
            Cancel
          </Button>
        </Section>

        <div className="billing-content-area">
          <Section
            flexDirection="column"
            alignItems="stretch"
            gap={0.25}
            padding={1}
            height="auto"
          >
            <InputLayouts.Vertical title="Seats">
              <InputNumber
                value={newSeatCount}
                onChange={setNewSeatCount}
                min={1}
                defaultValue={totalSeats}
                showReset
                variant={isBelowMinimum ? "error" : "primary"}
              />
            </InputLayouts.Vertical>

            {isBelowMinimum ? (
              <InputLayouts.ErrorTextLayout type="error">
                You cannot set seats below current{" "}
                <span className="font-semibold">{minRequiredSeats}</span> seats
                in use/pending.{" "}
                <Link
                  href="/admin/users"
                  className="underline hover:no-underline"
                >
                  Remove users
                </Link>{" "}
                first before adjusting seats.
              </InputLayouts.ErrorTextLayout>
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
          padding={1}
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
            main
            primary
            onClick={handleConfirm}
            disabled={
              isSubmitting || newSeatCount === totalSeats || isBelowMinimum
            }
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
        <Section gap={0.25} alignItems="start" height="auto" width="auto">
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
          gap={0.5}
          justifyContent="end"
          height="auto"
          width="auto"
        >
          <Button main tertiary href="/admin/users" leftIcon={SvgExternalLink}>
            View Users
          </Button>
          {!hideUpdateSeats && (
            <Button
              main
              secondary
              onClick={handleStartEdit}
              leftIcon={SvgPlus}
              disabled={isLoadingUsers || disabled || !billing}
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
        <Section
          flexDirection="row"
          gap={0.5}
          alignItems="stretch"
          height="auto"
        >
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
                main
                tertiary
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
                  main
                  tertiary
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
}: BillingDetailsViewProps) {
  const expirationState = billing ? getExpirationState(billing, license) : null;
  const disableBillingActions =
    isAirGapped || hasStripeError || isManualLicenseOnly;

  return (
    <Section gap={1} height="auto" width="full">
      {/* Stripe connection error banner */}
      {hasStripeError && (
        <Message
          static
          warning
          text="Unable to connect to Stripe payment portal."
          description="Check your internet connection or manually provide a license."
          close={false}
          className="w-full"
        />
      )}

      {/* Air-gapped mode info banner */}
      {isAirGapped && !hasStripeError && !isManualLicenseOnly && (
        <Message
          static
          info
          text="Air-gapped deployment"
          description="Online billing management is disabled. Contact support to update your subscription."
          close={false}
          className="w-full"
        />
      )}

      {/* Expiration banner */}
      {expirationState && (
        <Message
          static
          warning={expirationState.variant === "warning"}
          error={expirationState.variant === "error"}
          text={
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
          close={false}
          className="w-full"
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
