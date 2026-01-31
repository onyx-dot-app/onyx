"use client";

import { useState } from "react";
import Link from "next/link";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputNumber from "@/refresh-components/inputs/InputNumber";
import { SvgExternalLink, SvgPlus, SvgXOctagon } from "@opal/icons";
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import { updateSeatCount, claimLicense } from "@/lib/billing/svc";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import useUsers from "@/hooks/useUsers";
import * as InputLayouts from "@/layouts/input-layouts";
import { formatDateShort } from "@/lib/dateUtils";

interface SeatsCardProps {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onRefresh?: () => Promise<void>;
  /** Disable the Update Seats button (air-gapped or Stripe error) */
  disabled?: boolean;
}

export default function SeatsCard({
  billing,
  license,
  onRefresh,
  disabled,
}: SeatsCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch users data (includes both accepted and invited)
  const { data: usersData, isLoading: isLoadingUsers } = useUsers({
    includeApiKeys: false,
  });

  // Get seat data from either billing or license
  const totalSeats = billing?.seats ?? license?.seats ?? 0;
  const usedSeats = usersData?.accepted?.length ?? 0;
  const pendingSeats = usersData?.invited?.length ?? 0;

  const [newSeatCount, setNewSeatCount] = useState(totalSeats);

  // Calculate remaining seats
  const remainingSeats = Math.max(0, totalSeats - usedSeats - pendingSeats);

  // Minimum seats is used + pending (can't go below active users)
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

    // Don't allow confirming if below minimum
    if (isBelowMinimum) {
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await updateSeatCount({ new_seat_count: newSeatCount });
      // Re-claim license from control plane to get updated seat count (self-hosted only)
      if (!NEXT_PUBLIC_CLOUD_ENABLED) {
        await claimLicense();
      }
      // Wait for data refresh before closing edit mode
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

  if (isEditing) {
    return (
      <Card padding={0} alignItems="stretch" className="billing-card-enter">
        {/* Header */}
        <Section
          flexDirection="row"
          justifyContent="between"
          alignItems="start"
          padding={1}
          height="auto"
        >
          <Section gap={0.25} alignItems="start" height="auto" width="fit">
            <Text headingH3Muted text04>
              Update Seats
            </Text>
            <Text secondaryBody text03>
              Add or remove seats to reflect your team size.
            </Text>
          </Section>
          <Button main secondary onClick={handleCancel} disabled={isSubmitting}>
            Cancel
          </Button>
        </Section>

        {/* Content area */}
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
              <Section
                flexDirection="row"
                gap={0.25}
                alignItems="start"
                height="auto"
              >
                <SvgXOctagon
                  size={12}
                  className="stroke-status-error-05 mt-0.5 flex-shrink-0"
                />
                <Text secondaryBody className="text-status-error-05">
                  You cannot set seats below current{" "}
                  <Text
                    secondaryBody
                    className="text-status-error-05 font-semibold"
                  >
                    {minRequiredSeats}
                  </Text>{" "}
                  seats in use/pending.{" "}
                  <Link
                    href="/admin/users"
                    className="underline hover:no-underline"
                  >
                    Remove users
                  </Link>{" "}
                  first before adjusting seats.
                </Text>
              </Section>
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

        {/* Footer */}
        <Section
          flexDirection="row"
          alignItems="center"
          justifyContent="between"
          padding={1}
          height="auto"
        >
          {(() => {
            const nextBillingDate = formatDateShort(
              billing?.current_period_end
            );
            const seatCount = Math.abs(seatDifference);
            const seatWord = seatCount === 1 ? "seat" : "seats";

            if (isAdding) {
              return (
                <Text secondaryBody text03>
                  You will be billed for the{" "}
                  <Text secondaryBody text04>
                    {seatCount}
                  </Text>{" "}
                  additional {seatWord} at a pro-rated amount.
                </Text>
              );
            } else if (isRemoving) {
              return (
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
              );
            } else {
              return (
                <Text secondaryBody text03>
                  No changes to your billing.
                </Text>
              );
            }
          })()}
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
        {/* Left side - Seats info */}
        <Section gap={0.25} alignItems="start" height="auto" width="auto">
          <Text mainContentMuted text04>
            {totalSeats} Seats
          </Text>
          <Text secondaryBody text03>
            {usedSeats} in use • {pendingSeats} pending • {remainingSeats}{" "}
            remaining
          </Text>
        </Section>

        {/* Right side - Actions */}
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
          <Button
            main
            secondary
            onClick={handleStartEdit}
            leftIcon={SvgPlus}
            disabled={isLoadingUsers || disabled || !billing}
          >
            Update Seats
          </Button>
        </Section>
      </Section>
    </Card>
  );
}
