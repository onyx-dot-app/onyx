"use client";

import { useState, useCallback } from "react";
import { Button } from "@opal/components";
import { SvgUsers, SvgAlertTriangle, SvgLoader } from "@opal/icons";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import InputChipField from "@/refresh-components/inputs/InputChipField";
import type { ChipItem } from "@/refresh-components/inputs/InputChipField";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { inviteUsers } from "./svc";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InviteUsersModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function InviteUsersModal({
  open,
  onOpenChange,
}: InviteUsersModalProps) {
  const [chips, setChips] = useState<ChipItem[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  /** Parse a comma-separated string into de-duped ChipItems */
  function parseEmails(value: string, existing: ChipItem[]): ChipItem[] {
    const entries = value
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean);

    const newChips: ChipItem[] = [];
    for (const email of entries) {
      const alreadyAdded =
        existing.some((c) => c.label === email) ||
        newChips.some((c) => c.label === email);
      if (!alreadyAdded) {
        newChips.push({
          id: email,
          label: email,
          error: !EMAIL_REGEX.test(email),
        });
      }
    }
    return newChips;
  }

  function addEmail(value: string) {
    const newChips = parseEmails(value, chips);
    if (newChips.length > 0) {
      setChips((prev) => [...prev, ...newChips]);
    }
    setInputValue("");
  }

  function removeChip(id: string) {
    setChips((prev) => prev.filter((c) => c.id !== id));
  }

  const handleClose = useCallback(() => {
    onOpenChange(false);
    // Reset state after close animation
    setTimeout(() => {
      setChips([]);
      setInputValue("");
      setIsSubmitting(false);
    }, 200);
  }, [onOpenChange]);

  /** Intercept backdrop/ESC closes so state is always reset */
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        if (!isSubmitting) handleClose();
      } else {
        onOpenChange(next);
      }
    },
    [handleClose, isSubmitting, onOpenChange]
  );

  async function handleInvite() {
    // Flush any pending text in the input into chips synchronously
    const pending = inputValue.trim();
    const allChips = pending
      ? [...chips, ...parseEmails(pending, chips)]
      : chips;

    if (pending) {
      setChips(allChips);
      setInputValue("");
    }

    const validEmails = allChips.filter((c) => !c.error).map((c) => c.label);

    if (validEmails.length === 0) {
      toast.error("Please add at least one valid email address");
      return;
    }

    setIsSubmitting(true);
    try {
      await inviteUsers(validEmails);
      // Fire-and-forget revalidation so the invitee shows up immediately rather
      // than only on the next SWR focus revalidation. Not awaited: the invite
      // already succeeded, so a failing revalidation GET must not fall into the
      // catch below and surface an error toast / keep the modal open.
      void Promise.all([
        mutate(SWR_KEYS.invitedUsers),
        mutate(SWR_KEYS.acceptedUsers),
        mutate(SWR_KEYS.userCounts),
      ]).catch(() => {});
      toast.success(
        `Invited ${validEmails.length} user${validEmails.length > 1 ? "s" : ""}`
      );
      handleClose();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : "Failed to invite users"
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <Modal open={open} onOpenChange={handleOpenChange}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgUsers}
          title="Invite Users"
          onClose={isSubmitting ? undefined : handleClose}
        />

        <Modal.Body>
          <InputChipField
            chips={chips}
            onRemoveChip={removeChip}
            onAdd={addEmail}
            value={inputValue}
            onChange={setInputValue}
            placeholder="Add an email and press enter"
            layout="stacked"
          />
          {chips.some((c) => c.error) && (
            <div className="flex items-center gap-1 pt-1">
              <SvgAlertTriangle
                size={14}
                className="text-status-warning-05 shrink-0"
              />
              <Text secondaryBody text03>
                Some email addresses are invalid and will be skipped.
              </Text>
            </div>
          )}
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button
                disabled={isSubmitting}
                prominence="tertiary"
                onClick={handleClose}
              >
                Cancel
              </Button>
            }
            submit={
              <Button
                disabled={isSubmitting || chips.every((c) => c.error)}
                icon={
                  isSubmitting
                    ? () => <SvgLoader size={16} className="animate-spin" />
                    : undefined
                }
                onClick={handleInvite}
              >
                Invite
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
