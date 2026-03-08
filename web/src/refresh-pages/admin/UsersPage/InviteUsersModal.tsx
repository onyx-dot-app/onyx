"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import { SvgUsers, SvgUser } from "@opal/icons";
import { Disabled } from "@opal/core";
import Modal, { BasicModalFooter } from "@/refresh-components/Modal";
import InputChipField from "@/refresh-components/inputs/InputChipField";
import type { ChipItem } from "@/refresh-components/inputs/InputChipField";
import InputSelect from "@/refresh-components/inputs/InputSelect";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import { UserRole, USER_ROLE_LABELS } from "@/lib/types";
import { inviteUsers } from "./svc";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Roles available for invite — excludes curator-specific and system roles */
const INVITE_ROLES = [
  UserRole.BASIC,
  UserRole.ADMIN,
  UserRole.GLOBAL_CURATOR,
] as const;

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
  const [role, setRole] = useState<string>(UserRole.BASIC);
  const [isSubmitting, setIsSubmitting] = useState(false);

  function addEmail(value: string) {
    // Support comma-separated input
    const entries = value
      .split(",")
      .map((e) => e.trim().toLowerCase())
      .filter(Boolean);

    const newChips: ChipItem[] = [];
    for (const email of entries) {
      const alreadyAdded = chips.some((c) => c.label === email);
      if (!alreadyAdded) {
        newChips.push({ id: email, label: email });
      }
    }

    if (newChips.length > 0) {
      setChips((prev) => [...prev, ...newChips]);
    }
    setInputValue("");
  }

  function removeChip(id: string) {
    setChips((prev) => prev.filter((c) => c.id !== id));
  }

  function handleClose() {
    onOpenChange(false);
    // Reset state after close animation
    setTimeout(() => {
      setChips([]);
      setInputValue("");
      setRole(UserRole.BASIC);
    }, 200);
  }

  async function handleInvite() {
    const validEmails = chips
      .map((c) => c.label)
      .filter((e) => EMAIL_REGEX.test(e));

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

  const hasInvalidEmails = chips.some((c) => !EMAIL_REGEX.test(c.label));

  return (
    <Modal open={open} onOpenChange={onOpenChange}>
      <Modal.Content width="sm" height="fit">
        <Modal.Header
          icon={SvgUsers}
          title="Invite Users"
          onClose={handleClose}
        />

        <Modal.Body>
          <InputChipField
            chips={chips}
            onRemoveChip={removeChip}
            onAdd={addEmail}
            value={inputValue}
            onChange={(val) => {
              // Auto-add on comma
              if (val.includes(",")) {
                addEmail(val);
              } else {
                setInputValue(val);
              }
            }}
            placeholder="Add emails to invite, comma separated"
          />

          {hasInvalidEmails && (
            <Text as="p" secondaryBody className="text-status-error-text">
              Some entries are not valid email addresses and will be skipped.
            </Text>
          )}

          <div className="flex items-start justify-between w-full gap-4">
            <div className="flex flex-col gap-0.5">
              <Text as="p" mainUiAction text04>
                User Role
              </Text>
              <Text as="p" secondaryBody text03>
                Invite new users as
              </Text>
            </div>

            <div className="w-[200px]">
              <InputSelect value={role} onValueChange={setRole}>
                <InputSelect.Trigger />
                <InputSelect.Content>
                  {INVITE_ROLES.map((r) => (
                    <InputSelect.Item key={r} value={r} icon={SvgUser}>
                      {USER_ROLE_LABELS[r]}
                    </InputSelect.Item>
                  ))}
                </InputSelect.Content>
              </InputSelect>
            </div>
          </div>
        </Modal.Body>

        <Modal.Footer>
          <BasicModalFooter
            cancel={
              <Button prominence="tertiary" onClick={handleClose}>
                Cancel
              </Button>
            }
            submit={
              <Disabled disabled={isSubmitting || chips.length === 0}>
                <Button onClick={handleInvite}>Invite</Button>
              </Disabled>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
