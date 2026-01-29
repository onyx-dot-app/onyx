"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import IconButton from "@/refresh-components/buttons/IconButton";
import {
  SvgExternalLink,
  SvgPlus,
  SvgRevert,
  SvgChevronUp,
  SvgChevronDown,
} from "@opal/icons";
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import { updateSeatCount } from "@/lib/billing/actions";
import useUsers from "@/hooks/useUsers";
import * as InputLayouts from "@/layouts/input-layouts";
import { formatDateShort } from "@/lib/dateUtils";

interface SeatsCardProps {
  billing?: BillingInformation;
  license?: LicenseStatus;
  onRefresh?: () => void;
}

export default function SeatsCard({
  billing,
  license,
  onRefresh,
}: SeatsCardProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Fetch users data (includes both accepted and invited)
  const { data: usersData } = useUsers({ includeApiKeys: false });

  // Get seat data from either billing or license
  const totalSeats = billing?.seats ?? license?.seats ?? 0;
  // Use license used_seats if available, otherwise count accepted users
  const usedSeats = license?.used_seats ?? usersData?.accepted?.length ?? 0;

  const [newSeatCount, setNewSeatCount] = useState(totalSeats);

  // Calculate pending and remaining seats
  const pendingSeats = usersData?.invited?.length ?? 0;
  const remainingSeats = Math.max(0, totalSeats - usedSeats - pendingSeats);

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

    if (newSeatCount < usedSeats) {
      setError(`Cannot reduce below ${usedSeats} seats (currently in use)`);
      return;
    }

    setIsSubmitting(true);
    setError(null);

    try {
      await updateSeatCount({ new_seat_count: newSeatCount });
      setIsEditing(false);
      onRefresh?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update seats");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleReset = () => {
    setNewSeatCount(totalSeats);
  };

  const handleDecrement = () => {
    if (newSeatCount > usedSeats) {
      setNewSeatCount(newSeatCount - 1);
    }
  };

  const handleIncrement = () => {
    setNewSeatCount(newSeatCount + 1);
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
            <Text mainContentEmphasis>Update Seats</Text>
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
              <InputTypeIn
                value={newSeatCount.toString()}
                onChange={(e) => {
                  const val = parseInt(e.target.value, 10);
                  if (!isNaN(val) && val >= 0) {
                    setNewSeatCount(val);
                  }
                }}
                showClearButton={false}
                className="billing-seats-edit-input"
                rightSection={
                  <Section
                    flexDirection="row"
                    gap={0.5}
                    width="fit"
                    height="auto"
                    alignItems="center"
                  >
                    <IconButton
                      icon={SvgRevert}
                      onClick={handleReset}
                      disabled={newSeatCount === totalSeats}
                      internal
                    />
                    <div className="billing-stepper-container">
                      <IconButton
                        icon={SvgChevronUp}
                        onClick={handleIncrement}
                        internal
                        // iconClassName="w-3 h-3"
                      />
                      <IconButton
                        icon={SvgChevronDown}
                        onClick={handleDecrement}
                        disabled={newSeatCount <= usedSeats}
                        internal
                        // iconClassName="w-3 h-3"
                      />
                    </div>
                  </Section>
                }
              />
            </InputLayouts.Vertical>

            {seatDifference !== 0 && (
              <Text secondaryBody text03>
                {Math.abs(seatDifference)} seat
                {Math.abs(seatDifference) !== 1 ? "s" : ""} to be{" "}
                {isAdding ? "added" : "removed"}
              </Text>
            )}

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
            disabled={isSubmitting || newSeatCount === totalSeats}
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
          {billing && (
            <Button main secondary onClick={handleStartEdit} leftIcon={SvgPlus}>
              Update Seats
            </Button>
          )}
        </Section>
      </Section>
    </Card>
  );
}
