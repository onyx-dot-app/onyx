"use client";

import { useState, useCallback } from "react";
import { Button } from "@opal/components";
import { SvgUsers } from "@opal/icons";
import { Disabled } from "@opal/core";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import InputChipField from "@/refresh-components/inputs/InputChipField";
import type { ChipItem } from "@/refresh-components/inputs/InputChipField";
import { toast } from "@/hooks/useToast";
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
    }, 200);
  }, [onOpenChange]);

  /** Intercept backdrop/ESC closes so state is always reset */
  const handleOpenChange = useCallback(
    (next: boolean) => {
      if (!next) {
        handleClose();
      } else {
        onOpenChange(next);
      }
    },
    [handleClose, onOpenChange]
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
            placeholder="Add emails to invite, comma separated"
            layout="stacked"
          />
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Disabled disabled={isSubmitting}>
                <Button prominence="tertiary" onClick={handleClose}>
                  Cancel
                </Button>
              </Disabled>
            }
            submit={
              <Disabled
                disabled={
                  isSubmitting ||
                  chips.length === 0 ||
                  chips.every((c) => c.error)
                }
              >
                <Button onClick={handleInvite}>Invite</Button>
              </Disabled>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
