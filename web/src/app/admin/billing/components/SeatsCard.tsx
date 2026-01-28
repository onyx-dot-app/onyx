"use client";

import { useState } from "react";
import { Section } from "@/layouts/general-layouts";
import Card from "@/refresh-components/cards/Card";
import Button from "@/refresh-components/buttons/Button";
import Text from "@/refresh-components/texts/Text";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import { SvgExternalLink, SvgMinus, SvgPlus } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import { BillingInformation, LicenseStatus } from "@/lib/billing/interfaces";
import { updateSeatCount } from "@/lib/billing/actions";

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

  // Get seat data from either billing or license
  const totalSeats = billing?.seats ?? license?.seats ?? 0;
  const usedSeats = license?.used_seats ?? 0;

  const [newSeatCount, setNewSeatCount] = useState(totalSeats);

  // Calculate pending and remaining seats
  const pendingSeats = 0; // This would need to come from an invite system
  const remainingSeats = totalSeats - usedSeats - pendingSeats;

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

  const handleDecrement = () => {
    if (newSeatCount > usedSeats) {
      setNewSeatCount(newSeatCount - 1);
    }
  };

  const handleIncrement = () => {
    setNewSeatCount(newSeatCount + 1);
  };

  if (isEditing) {
    return (
      <Card>
        <Section gap={1} alignItems="start" height="auto">
          <Section gap={0.25} alignItems="start" height="auto">
            <Text mainContentEmphasis>Update Seats</Text>
            <Text secondaryBody text03>
              Add or remove seats to reflect your team size.
            </Text>
          </Section>

          <Section
            flexDirection="row"
            gap={0.5}
            justifyContent="start"
            alignItems="center"
            height="auto"
          >
            <IconButton
              icon={SvgMinus}
              onClick={handleDecrement}
              disabled={newSeatCount <= usedSeats}
              main
              secondary
            />
            <InputTypeIn
              value={newSeatCount.toString()}
              onChange={(e) => {
                const val = parseInt(e.target.value, 10);
                if (!isNaN(val) && val >= 0) {
                  setNewSeatCount(val);
                }
              }}
              className="billing-seats-input"
              showClearButton={false}
            />
            <IconButton
              icon={SvgPlus}
              onClick={handleIncrement}
              main
              secondary
            />
          </Section>

          <Text secondaryBody text03>
            {usedSeats} seats in use
          </Text>

          {error && (
            <Text secondaryBody text02>
              {error}
            </Text>
          )}

          <Section
            flexDirection="row"
            gap={0.5}
            justifyContent="start"
            height="auto"
          >
            <Button
              main
              tertiary
              onClick={handleCancel}
              disabled={isSubmitting}
            >
              Cancel
            </Button>
            <Button
              main
              primary
              onClick={handleConfirm}
              disabled={isSubmitting || newSeatCount === totalSeats}
            >
              {isSubmitting ? "Saving..." : "Confirm Change"}
            </Button>
          </Section>
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
          <Text mainContentEmphasis>{totalSeats} Seats</Text>
          <Text secondaryBody text03>
            {usedSeats} in use
            {pendingSeats > 0 && ` \u2022 ${pendingSeats} pending`}
            {remainingSeats > 0 && ` \u2022 ${remainingSeats} remaining`}
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
          <Button main tertiary href="/admin/users" rightIcon={SvgExternalLink}>
            View Users
          </Button>
          {billing && (
            <Button main secondary onClick={handleStartEdit}>
              Update Seats
            </Button>
          )}
        </Section>
      </Section>
    </Card>
  );
}
