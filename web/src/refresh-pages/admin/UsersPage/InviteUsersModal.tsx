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
import { useTranslation } from "react-i18next";

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
  const { t } = useTranslation();

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
      toast.error(t("admin.users.add_valid_email_error"));
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
        validEmails.length === 1
          ? t("admin.users.invite_success_single")
          : t("admin.users.invite_success_plural", { count: validEmails.length })
      );
      handleClose();
    } catch (err) {
      toast.error(
        err instanceof Error ? err.message : t("admin.users.invite_failed")
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
          title={t("admin.users.invite_title")}
          onClose={isSubmitting ? undefined : handleClose}
        />

        <Modal.Body>
          <InputChipField
            chips={chips}
            onRemoveChip={removeChip}
            onAdd={addEmail}
            value={inputValue}
            onChange={setInputValue}
            placeholder={t("admin.users.email_placeholder")}
            layout="stacked"
          />
          {chips.some((c) => c.error) && (
            <div className="flex items-center gap-1 pt-1">
              <SvgAlertTriangle
                size={14}
                className="text-status-warning-05 shrink-0"
              />
              <Text secondaryBody text03>
                {t("admin.users.invalid_emails_warning")}
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
                {t("general.cancel")}
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
                {t("general.invite")}
              </Button>
            }
          />
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
