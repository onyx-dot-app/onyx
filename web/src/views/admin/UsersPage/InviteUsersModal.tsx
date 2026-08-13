"use client";

import { useState, useCallback } from "react";
import {
  BasicModalFooter,
  Button,
  InputTags,
  Modal,
  type TagItem,
} from "@opal/components";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgSimpleLoader,
  SvgUsers,
} from "@opal/icons";
import type { ColorTypes, IconFunctionComponent } from "@opal/types";
import { Content, toast } from "@opal/layouts";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { inviteUsers } from "./svc";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Whitespace and commas both end an address, so either one commits a tag. */
const SEPARATOR_REGEX = /[\s,]+/;

/** The field in the mock is three tag rows tall. */
const EMAIL_FIELD_ROWS = 3;

function isValidEmail(value: string): boolean {
  return EMAIL_REGEX.test(value);
}

function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
}

/** Tags for entries not already present, de-duped case-insensitively. */
function buildTags(entries: string[], existing: TagItem[]): TagItem[] {
  const added: TagItem[] = [];
  for (const entry of entries) {
    const email = normalizeEmail(entry);
    const seen =
      existing.some((tag) => tag.id === email) ||
      added.some((tag) => tag.id === email);
    if (email && !seen) {
      added.push({ id: email, label: email, error: !isValidEmail(email) });
    }
  }
  return added;
}

function buildMessage(
  tags: TagItem[],
  pendingEmail: string,
  validCount: number
): FieldMessage | null {
  if (tags.length === 0 && pendingEmail === "") return null;
  if (tags.some((tag) => tag.error)) {
    return {
      icon: SvgAlertTriangle,
      color: "muted-warning",
      text: "Some email addresses are invalid and will be skipped.",
    };
  }
  if (validCount === 0) {
    return {
      icon: SvgAlertTriangle,
      color: "muted-warning",
      text: "Enter a valid email address to invite.",
    };
  }
  return {
    icon: SvgCheckCircle,
    color: "muted-success",
    text: `${validCount} email${validCount > 1 ? "s" : ""} to invite`,
  };
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface InviteUsersModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

interface FieldMessage {
  icon: IconFunctionComponent;
  color: ColorTypes;
  text: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function InviteUsersModal({
  open,
  onOpenChange,
}: InviteUsersModalProps) {
  const [tags, setTags] = useState<TagItem[]>([]);
  const [inputValue, setInputValue] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  function addTags(entries: string[]) {
    setTags((prev) => {
      const added = buildTags(entries, prev);
      return added.length > 0 ? [...prev, ...added] : prev;
    });
  }

  function removeTag(id: string) {
    setTags((prev) => prev.filter((tag) => tag.id !== id));
  }

  /** Commits every separator-terminated address, keeping the trailing text. */
  function handleInputChange(next: string) {
    if (!SEPARATOR_REGEX.test(next)) {
      setInputValue(next);
      return;
    }
    const parts = next.split(SEPARATOR_REGEX);
    const trailing = parts.pop() ?? "";
    addTags(parts);
    setInputValue(trailing);
  }

  function handleAdd(value: string) {
    addTags([value]);
    setInputValue("");
  }

  const pendingEmail = normalizeEmail(inputValue);
  const pendingIsValid =
    isValidEmail(pendingEmail) && !tags.some((tag) => tag.id === pendingEmail);
  const validCount =
    tags.filter((tag) => !tag.error).length + (pendingIsValid ? 1 : 0);
  const message = buildMessage(tags, pendingEmail, validCount);

  const handleClose = useCallback(() => {
    onOpenChange(false);
    // Reset state after close animation
    setTimeout(() => {
      setTags([]);
      setInputValue("");
      setIsSubmitting(false);
    }, 200);
  }, [onOpenChange]);

  /** Route backdrop/ESC closes through handleClose, and block them mid-submit. */
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
    // setTags is not visible until the next render, so submit the locally built list.
    const allTags = [...tags, ...buildTags([inputValue], tags)];
    setTags(allTags);
    setInputValue("");

    const validEmails = allTags
      .filter((tag) => !tag.error)
      .map((tag) => tag.label);

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

        <Modal.Body alignItems="stretch" gap={1}>
          <InputTags
            tags={tags}
            onRemoveTag={removeTag}
            onAdd={handleAdd}
            value={inputValue}
            onChange={handleInputChange}
            placeholder="Add emails to invite, space or comma separated"
            minRows={EMAIL_FIELD_ROWS}
            autoFocus
          />
          {message && (
            <Content
              sizePreset="secondary"
              variant="body"
              icon={message.icon}
              title={message.text}
              color={message.color}
              role="status"
            />
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
                disabled={isSubmitting || validCount === 0}
                icon={isSubmitting ? SvgSimpleLoader : undefined}
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
