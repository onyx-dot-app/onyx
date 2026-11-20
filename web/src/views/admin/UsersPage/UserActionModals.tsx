"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import {
  Button,
  CopyButton,
  InputTypeIn,
  MessageCard,
  Text,
} from "@opal/components";
import { IconLoader } from "@opal/loaders";
import { richNodes } from "@opal/utils";
import {
  SvgArrowUpRight,
  SvgUserPlus,
  SvgUserX,
  SvgXCircle,
  SvgKey,
} from "@opal/icons";
import { ConfirmationModalLayout, Section } from "@opal/layouts";
import { toast } from "@opal/layouts";
import { useNavigation } from "@opal/navigation";
import { errorHandlingFetcher, FetchError } from "@/lib/fetcher";
import useSWR from "swr";
import { SWR_KEYS } from "@/lib/swr-keys";
import { AccountType } from "@/lib/types";
import { deleteMarketplace } from "@/lib/marketplaces/api";
import {
  TransferOwnershipView,
  type TransferOwnershipTarget,
} from "@/sections/modals/TransferOwnershipView";
import {
  deactivateUser,
  activateUser,
  deleteUser,
  cancelInvite,
  resetPassword,
  transferPrivatePlugins,
} from "@/views/admin/UsersPage/svc";
import type {
  FullUserSnapshot,
  PrivatePlugin,
} from "@/views/admin/UsersPage/types";

// ---------------------------------------------------------------------------
// Shared helper
// ---------------------------------------------------------------------------

async function runAction(
  action: () => Promise<void>,
  successMessage: string,
  errorMessage: string,
  onDone: () => void,
  setIsSubmitting: (v: boolean) => void,
  /** Shows a custom toast for `err` and returns true, or returns false. */
  showErrorToast?: (err: unknown) => boolean
) {
  setIsSubmitting(true);
  try {
    await action();
    onDone();
    toast.success(successMessage);
  } catch (err) {
    if (!showErrorToast?.(err)) {
      toast.error(err instanceof Error ? err.message : errorMessage);
    }
  } finally {
    setIsSubmitting(false);
  }
}

/** Renders the email inside a confirmation sentence with emphasis. */
function emailTag(chunks: ReactNode) {
  return (
    <Text as="span" color="text-05">
      {richNodes(chunks)}
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
  const { appName } = useSettings();
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
      <Text as="p" color="text-03">
        {richNodes(
          t.rich("cancelInviteModal.description", {
            email,
            strong: emailTag,
            appName,
          })
        )}
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
  const { appName } = useSettings();
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
      <Text as="p" color="text-03">
        {richNodes(
          t.rich("deactivateModal.description", {
            email,
            strong: emailTag,
            appName,
          })
        )}
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
  const { appName } = useSettings();
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
      <Text as="p" color="text-03">
        {richNodes(
          t.rich("activateModal.description", {
            email,
            strong: emailTag,
            appName,
          })
        )}
      </Text>
    </ConfirmationModalLayout>
  );
}

// ---------------------------------------------------------------------------
// Delete User Modal
// ---------------------------------------------------------------------------

const PRIVATE_SKILLS_TOAST_ID = "delete-user-private-skills";

/**
 * Closes the private-skills conflict toast when the Users page unmounts, so
 * the toast leaves together with the page and not over it.
 */
export function useClosePrivateSkillsToastOnLeave() {
  useEffect(() => () => toast.dismiss(PRIVATE_SKILLS_TOAST_ID), []);
}

interface DeleteUserModalProps {
  email: string;
  onClose: () => void;
  onMutate: () => void;
}

function isNamedItem(value: unknown): value is PrivatePlugin {
  return (
    typeof value === "object" &&
    value !== null &&
    "id" in value &&
    typeof value.id === "string" &&
    "name" in value &&
    typeof value.name === "string"
  );
}

/** The items of one list in a refused delete, or null for another error. */
function conflictItemsFrom(
  err: unknown,
  key: "private_plugins" | "personal_marketplaces"
): PrivatePlugin[] | null {
  if (!(err instanceof FetchError) || err.info?.error_code !== "CONFLICT") {
    return null;
  }
  const info: object = err.info;
  const items = key in info ? (info as Record<string, unknown>)[key] : null;
  if (!Array.isArray(items) || items.length === 0) return null;
  return items.filter(isNamedItem);
}

export function DeleteUserModal({
  email,
  onClose,
  onMutate,
}: DeleteUserModalProps) {
  const t = useTranslations("admin.users");
  const { appName } = useSettings();
  const navigation = useNavigation();
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [privatePlugins, setPrivatePlugins] = useState<PrivatePlugin[] | null>(
    null
  );
  const [personalMarketplaces, setPersonalMarketplaces] = useState<
    PrivatePlugin[] | null
  >(null);
  const [transferTarget, setTransferTarget] =
    useState<TransferOwnershipTarget>(null);
  const owners = useSWR<FullUserSnapshot[]>(
    privatePlugins ? SWR_KEYS.acceptedUsers : null,
    errorHandlingFetcher
  );
  // The server accepts only an active standard user as the new owner.
  const candidates = (owners.data ?? []).filter(
    (user) =>
      user.email !== email &&
      user.is_active &&
      user.account_type === AccountType.STANDARD
  );

  function showPrivateSkillsToast(err: unknown): boolean {
    const plugins = conflictItemsFrom(err, "private_plugins");
    if (plugins) {
      setPrivatePlugins(plugins);
      return true;
    }
    const marketplaces = conflictItemsFrom(err, "personal_marketplaces");
    if (marketplaces) {
      setPrivatePlugins(null);
      setPersonalMarketplaces(marketplaces);
      return true;
    }
    if (!(err instanceof FetchError) || err.info?.error_code !== "CONFLICT") {
      return false;
    }
    toast.error(t("deleteModal.toasts.blockedBySkills"), {
      id: PRIVATE_SKILLS_TOAST_ID,
      description: err.message,
      duration: Infinity,
      action: {
        icon: SvgArrowUpRight,
        label: t("deleteModal.toasts.openSkills"),
        onClick: () => navigation.go("/admin/skills"),
      },
    });
    return true;
  }

  function onDeleted() {
    toast.dismiss(PRIVATE_SKILLS_TOAST_ID);
    onMutate();
    onClose();
  }

  async function transferAllThenDelete(newOwner: string) {
    const result = await transferPrivatePlugins(email, newOwner);
    // The transfer is committed, so report the renames even if the delete fails.
    if (result.renames.length > 0) {
      toast.info(t("deleteModal.toasts.renamed"), {
        description: result.renames
          .map((rename) => `${rename.old_name} → ${rename.new_name}`)
          .join(", "),
      });
    }
    await deleteUser(email);
  }

  async function removeMarketplacesThenDelete(marketplaces: PrivatePlugin[]) {
    for (const marketplace of marketplaces) {
      try {
        await deleteMarketplace(marketplace.id);
      } catch (err) {
        // A retry after a partial failure finds some already removed.
        if (!(err instanceof FetchError) || err.status !== 404) throw err;
      }
    }
    await deleteUser(email);
  }

  if (personalMarketplaces) {
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
                () => removeMarketplacesThenDelete(personalMarketplaces),
                t("deleteModal.toasts.success"),
                t("modals.toasts.error"),
                onDeleted,
                setIsSubmitting,
                showPrivateSkillsToast
              )
            }
          >
            {t("deleteModal.marketplaces.submit.label")}
          </Button>
        }
      >
        <Section gap={3} height="auto" alignItems="stretch">
          <Text as="p" color="text-03">
            {richNodes(
              t.rich("deleteModal.marketplaces.description", {
                email,
                count: personalMarketplaces.length,
                strong: emailTag,
              })
            )}
          </Text>
          <Section gap={0.5} height="auto" alignItems="start">
            {personalMarketplaces.map((marketplace) => (
              <Text key={marketplace.id} font="main-ui-body" color="text-04">
                {marketplace.name}
              </Text>
            ))}
          </Section>
        </Section>
      </ConfirmationModalLayout>
    );
  }

  if (privatePlugins) {
    const newOwner = transferTarget?.type === "user" ? transferTarget : null;
    return (
      <ConfirmationModalLayout
        icon={(props) => (
          <SvgUserX {...props} className="text-action-danger-05" />
        )}
        title={t("deleteModal.title")}
        onClose={isSubmitting ? undefined : onClose}
        submit={
          <Button
            disabled={isSubmitting || !newOwner}
            variant="danger"
            onClick={() => {
              if (!newOwner) return;
              runAction(
                () =>
                  transferAllThenDelete(newOwner.value.replace("user-", "")),
                t("deleteModal.toasts.success"),
                t("modals.toasts.error"),
                onDeleted,
                setIsSubmitting,
                showPrivateSkillsToast
              );
            }}
          >
            {t("deleteModal.transfer.submit.label")}
          </Button>
        }
      >
        <Section gap={3} height="auto" alignItems="stretch">
          <Text as="p" color="text-03">
            {richNodes(
              t.rich("deleteModal.transfer.description", {
                email,
                count: privatePlugins.length,
                strong: emailTag,
              })
            )}
          </Text>
          <Section gap={0.5} height="auto" alignItems="start">
            {privatePlugins.map((plugin) => (
              <Text key={plugin.id} font="main-ui-body" color="text-04">
                {plugin.name}
              </Text>
            ))}
          </Section>
          {owners.isLoading ? (
            <IconLoader />
          ) : owners.error ? (
            <Section alignItems="start" gap={2} height="auto">
              <MessageCard
                variant="error"
                title={t("deleteModal.transfer.ownersLoadFailed")}
              />
              <Button
                prominence="secondary"
                onClick={() => void owners.mutate()}
              >
                {t("deleteModal.transfer.retry")}
              </Button>
            </Section>
          ) : (
            <TransferOwnershipView
              agent={null}
              groups={[]}
              onSelectedTargetChange={setTransferTarget}
              selectedTarget={transferTarget}
              users={candidates.map((user) => ({
                id: user.id,
                email: user.email,
              }))}
            />
          )}
        </Section>
      </ConfirmationModalLayout>
    );
  }

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
              onDeleted,
              setIsSubmitting,
              showPrivateSkillsToast
            )
          }
        >
          {t("deleteModal.submit.label")}
        </Button>
      }
    >
      <Text as="p" color="text-03">
        {richNodes(
          t.rich("deleteModal.description", {
            email,
            strong: emailTag,
            appName,
          })
        )}
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

  // Closing keeps `newPassword`, so the card fades out showing it; the modal
  // unmounts after its exit, so the next open starts fresh.

  return (
    <ConfirmationModalLayout
      icon={SvgKey}
      title={
        newPassword
          ? t("resetPasswordModal.successTitle")
          : t("resetPasswordModal.title")
      }
      onClose={isSubmitting ? undefined : onClose}
      hideCancel={!!newPassword}
      submit={
        newPassword ? (
          <Button onClick={onClose}>
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
          <Text as="p" color="text-03">
            {richNodes(
              t.rich("resetPasswordModal.successDescription", {
                email,
                strong: emailTag,
              })
            )}
          </Text>
          <div className="font-main-ui-mono relative">
            <InputTypeIn value={newPassword} variant="readOnly" />
            {/* The field has no right slot, so the button sits over it. */}
            <div className="absolute inset-y-0 end-1 flex items-center">
              <CopyButton
                size="sm"
                getCopyText={() => newPassword}
                tooltip={t("resetPasswordModal.copyButton.label")}
                aria-label={t("resetPasswordModal.copyButton.label")}
              />
            </div>
          </div>
        </div>
      ) : (
        <Text as="p" color="text-03">
          {richNodes(
            t.rich("resetPasswordModal.description", {
              email,
              strong: emailTag,
            })
          )}
        </Text>
      )}
    </ConfirmationModalLayout>
  );
}
