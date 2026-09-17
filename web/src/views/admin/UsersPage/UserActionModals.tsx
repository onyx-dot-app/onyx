"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@opal/components";
import { SvgUserPlus, SvgUserX, SvgXCircle, SvgKey } from "@opal/icons";
import { ConfirmationModalLayout } from "@opal/layouts";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@opal/layouts";
import {
  deactivateUser,
  activateUser,
  deleteUser,
  cancelInvite,
  resetPassword,
} from "./svc";

// ---------------------------------------------------------------------------
// Shared helper
// ---------------------------------------------------------------------------

async function runAction(
  action: () => Promise<void>,
  successMessage: string,
  errorMessage: string,
  onDone: () => void,
  setIsSubmitting: (v: boolean) => void
) {
  setIsSubmitting(true);
  try {
    await action();
    onDone();
    toast.success(successMessage);
  } catch (err) {
    toast.error(err instanceof Error ? err.message : errorMessage);
  } finally {
    setIsSubmitting(false);
  }
}

/** Renders the email inside a confirmation sentence with emphasis. */
function emailTag(chunks: ReactNode) {
  return (
    <Text as="span" text05>
      {chunks}
    </Text>
  );
}

// ---------------------------------------------------------------------------
// Cancel Invite Modal
// ---------------------------------------------------------------------------

interface CancelInviteModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function CancelInviteModal({
  email,
  onClose,
  onMutate,
}: CancelInviteModalProps) {
  const t = useTranslations("admin.users");
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={(props) => (
        <SvgUserX {...props} className="text-action-danger-05" />
      )}
      title={t("cancelInviteModal.title")}
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          variant="danger"
          onClick={() =>
            runAction(
              () => cancelInvite(email),
              t("cancelInviteModal.toasts.success"),
              t("modals.toasts.error"),
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          {t("cancelInviteModal.submit.label")}
        </Button>
      }
    >
      <Text as="p" text03>
        {t.rich("cancelInviteModal.description", { email, strong: emailTag })}
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Deactivate User Modal
// ---------------------------------------------------------------------------

interface DeactivateUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function DeactivateUserModal({
  email,
  onClose,
  onMutate,
}: DeactivateUserModalProps) {
  const t = useTranslations("admin.users");
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={(props) => (
        <SvgUserX {...props} className="text-action-danger-05" />
      )}
      title={t("deactivateModal.title")}
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          variant="danger"
          onClick={() =>
            runAction(
              () => deactivateUser(email),
              t("deactivateModal.toasts.success"),
              t("modals.toasts.error"),
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          {t("deactivateModal.submit.label")}
        </Button>
      }
    >
      <Text as="p" text03>
        {t.rich("deactivateModal.description", { email, strong: emailTag })}
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Activate User Modal
// ---------------------------------------------------------------------------

interface ActivateUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function ActivateUserModal({
  email,
  onClose,
  onMutate,
}: ActivateUserModalProps) {
  const t = useTranslations("admin.users");
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={SvgUserPlus}
      title={t("activateModal.title")}
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          onClick={() =>
            runAction(
              () => activateUser(email),
              t("activateModal.toasts.success"),
              t("modals.toasts.error"),
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          {t("activateModal.submit.label")}
        </Button>
      }
    >
      <Text as="p" text03>
        {t.rich("activateModal.description", { email, strong: emailTag })}
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Delete User Modal
// ---------------------------------------------------------------------------

interface DeleteUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

export function DeleteUserModal({
  email,
  onClose,
  onMutate,
}: DeleteUserModalProps) {
  const t = useTranslations("admin.users");
  const [isSubmitting, setIsSubmitting] = useState(false);

  return (
    <ConfirmationModalLayout
      icon={(props) => (
        <SvgUserX {...props} className="text-action-danger-05" />
      )}
      title={t("deleteModal.title")}
      onClose={isSubmitting ? undefined : onClose}
      submit={
        <Button
          disabled={isSubmitting}
          variant="danger"
          onClick={() =>
            runAction(
              () => deleteUser(email),
              t("deleteModal.toasts.success"),
              t("modals.toasts.error"),
              () => {
                onMutate();
                onClose();
              },
              setIsSubmitting
            )
          }
        >
          {t("deleteModal.submit.label")}
        </Button>
      }
    >
      <Text as="p" text03>
        {t.rich("deleteModal.description", { email, strong: emailTag })}
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Reset Password Modal
// ---------------------------------------------------------------------------

interface ResetPasswordModalProps {
  email: string;
  onClose: () => void;
}

export function ResetPasswordModal({
  email,
  onClose,
}: ResetPasswordModalProps) {
  const t = useTranslations("admin.users");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [newPassword, setNewPassword] = useState<string | null>(null);

  const handleClose = () => {
    onClose();
    setNewPassword(null);
  };

  return (
    <ConfirmationModalLayout
      icon={SvgKey}
      title={
        newPassword
          ? t("resetPasswordModal.successTitle")
          : t("resetPasswordModal.title")
      }
      onClose={isSubmitting ? undefined : handleClose}
      submit={
        newPassword ? (
          <Button onClick={handleClose}>
            {t("resetPasswordModal.doneButton.label")}
          </Button>
        ) : (
          <Button
            disabled={isSubmitting}
            variant="danger"
            onClick={async () => {
              setIsSubmitting(true);
              try {
                const result = await resetPassword(email);
                setNewPassword(result.new_password);
              } catch (err) {
                toast.error(
                  err instanceof Error
                    ? err.message
                    : t("resetPasswordModal.toasts.error")
                );
              } finally {
                setIsSubmitting(false);
              }
            }}
          >
            {t("resetPasswordModal.submit.label")}
          </Button>
        )
      }
    >
      {newPassword ? (
        <div className="flex flex-col gap-2">
          <Text as="p" text03>
            {t.rich("resetPasswordModal.successDescription", {
              email,
              strong: emailTag,
            })}
          </Text>
          <code className="rounded-xs bg-background-neutral-02 px-3 py-2 text-sm select-all">
            {newPassword}
          </code>
        </div>
      ) : (
        <Text as="p" text03>
          {t.rich("resetPasswordModal.description", {
            email,
            strong: emailTag,
          })}
        </Text>
      )}
    </ConfirmationModalLayout>
  );
}
