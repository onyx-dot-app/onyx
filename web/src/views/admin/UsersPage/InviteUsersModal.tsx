"use client";

import { useState, useCallback } from "react";
import {
  BasicModalFooter,
  Button,
  InputTags,
  Modal,
  Text,
} from "@opal/components";
import type { TagItem } from "@opal/components";
import {
  SvgAlertTriangle,
  SvgCheckCircle,
  SvgLoader,
  SvgUsers,
} from "@opal/icons";
import type { IconFunctionComponent } from "@opal/types";
import { Section, toast } from "@opal/layouts";
import { mutate } from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { inviteUsers } from "./svc";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const EMAIL_REGEX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Whitespace and commas both end an address, so typing either commits a tag. */
const SEPARATOR_REGEX = /[\s,]+/;

/** Tag rows the field is tall enough to show before it grows. */
const EMAIL_FIELD_ROWS = 3;

function isValidEmail(value: string): boolean {
  return EMAIL_REGEX.test(value);
}

function normalizeEmail(value: string): string {
  return value.trim().toLowerCase();
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
  iconClassName: string;
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

  function addTags(entries: string[]) {
    const added = buildTags(entries, tags);
    if (added.length > 0) setTags((prev) => [...prev, ...added]);
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

  function buildMessage(): FieldMessage | null {
    if (tags.length === 0 && pendingEmail === "") return null;
    if (tags.some((tag) => tag.error)) {
      return {
        icon: SvgAlertTriangle,
        iconClassName: "text-status-warning-05",
        text: "Some email addresses are invalid and will be skipped.",
      };
    }
    if (validCount === 0) {
      return {
        icon: SvgAlertTriangle,
        iconClassName: "text-status-warning-05",
        text: "Enter a valid email address to invite.",
      };
    }
    return {
      icon: SvgCheckCircle,
      iconClassName: "text-status-success-05",
      text: `${validCount} email${validCount > 1 ? "s" : ""} to invite`,
    };
  }

  const message = buildMessage();

  const handleClose = useCallback(() => {
    onOpenChange(false);
    // Reset state after close animation
    setTimeout(() => {
      setTags([]);
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
    // Flush any pending text in the input into tags synchronously
    const allTags = pendingEmail
      ? [...tags, ...buildTags([pendingEmail], tags)]
      : tags;

    if (pendingEmail) {
      setTags(allTags);
      setInputValue("");
    }

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

        <Modal.Body>
          <Section
            flexDirection="column"
            alignItems="stretch"
            height="fit"
            gap={1}
          >
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
              <Section
                flexDirection="row"
                alignItems="start"
                justifyContent="start"
                height="fit"
                gap={0.5}
              >
                <Section
                  width={1}
                  height={1}
                  padding={0.5}
                  gap={0}
                  className="shrink-0"
                >
                  <message.icon size={12} className={message.iconClassName} />
                </Section>
                <Text font="secondary-body" color="text-03">
                  {message.text}
                </Text>
              </Section>
            )}
          </Section>
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
