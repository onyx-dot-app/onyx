"use client";

import { useState } from "react";
import { Button } from "@opal/components";
import {
  SvgMoreHorizontal,
  SvgUsers,
  SvgXCircle,
  SvgUserCheck,
  SvgUserPlus,
  SvgUserX,
  SvgKey,
} from "@opal/icons";
import { Disabled } from "@opal/core";
import Popover from "@/refresh-components/Popover";
import Separator from "@/refresh-components/Separator";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { Section } from "@/layouts/general-layouts";
import Text from "@/refresh-components/texts/Text";
import { UserStatus } from "@/lib/types";
import { toast } from "@/hooks/useToast";
import {
  deactivateUser,
  activateUser,
  deleteUser,
  cancelInvite,
  approveRequest,
  resetPassword,
} from "./svc";
import EditUserModal from "./EditUserModal";
import type { UserRow } from "./interfaces";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

enum Modal {
  DEACTIVATE = "deactivate",
  ACTIVATE = "activate",
  DELETE = "delete",
  CANCEL_INVITE = "cancelInvite",
  EDIT_GROUPS = "editGroups",
  RESET_PASSWORD = "resetPassword",
}

interface UserRowActionsProps {
  user: UserRow;
  onMutate: () => void;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export default function UserRowActions({
  user,
  onMutate,
}: UserRowActionsProps) {
  const [modal, setModal] = useState<Modal | null>(null);
  const [popoverOpen, setPopoverOpen] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [newPassword, setNewPassword] = useState<string | null>(null);

  async function handleAction(
    action: () => Promise<void>,
    successMessage: string
  ) {
    setIsSubmitting(true);
    try {
      await action();
      onMutate();
      toast.success(successMessage);
      setModal(null);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "An error occurred");
    } finally {
      setIsSubmitting(false);
    }
  }

  const openModal = (type: Modal) => {
    setPopoverOpen(false);
    setModal(type);
  };

  // Status-aware action menus
  const actionButtons = (() => {
    // SCIM-managed users get limited actions — most changes would be
    // overwritten on the next IdP sync.
    if (user.is_scim_synced) {
      return (
        <>
          {user.id && (
            <Button
              prominence="tertiary"
              icon={SvgUsers}
              onClick={() => openModal(Modal.EDIT_GROUPS)}
            >
              Groups &amp; Roles
            </Button>
          )}
          <Disabled disabled>
            <Button prominence="tertiary" variant="danger" icon={SvgUserX}>
              Deactivate User
            </Button>
          </Disabled>
          <Separator paddingXRem={0.5} />
          <Text as="p" secondaryBody text03 className="px-3 py-1">
            This is a synced SCIM user managed by your identity provider.
          </Text>
        </>
      );
    }

    switch (user.status) {
      case UserStatus.INVITED:
        return (
          <Button
            prominence="tertiary"
            variant="danger"
            icon={SvgXCircle}
            onClick={() => openModal(Modal.CANCEL_INVITE)}
          >
            Cancel Invite
          </Button>
        );

      case UserStatus.REQUESTED:
        return (
          <Button
            prominence="tertiary"
            icon={SvgUserCheck}
            onClick={() => {
              setPopoverOpen(false);
              handleAction(
                () => approveRequest(user.email),
                "Request approved"
              );
            }}
          >
            Approve
          </Button>
        );

      case UserStatus.ACTIVE:
        return (
          <>
            {user.id && (
              <Button
                prominence="tertiary"
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
              >
                Groups &amp; Roles
              </Button>
            )}
            <Button
              prominence="tertiary"
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
            >
              Reset Password
            </Button>
            <Separator paddingXRem={0.5} />
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DEACTIVATE)}
            >
              Deactivate User
            </Button>
          </>
        );

      case UserStatus.INACTIVE:
        return (
          <>
            {user.id && (
              <Button
                prominence="tertiary"
                icon={SvgUsers}
                onClick={() => openModal(Modal.EDIT_GROUPS)}
              >
                Groups &amp; Roles
              </Button>
            )}
            <Button
              prominence="tertiary"
              icon={SvgKey}
              onClick={() => openModal(Modal.RESET_PASSWORD)}
            >
              Reset Password
            </Button>
            <Separator paddingXRem={0.5} />
            <Button
              prominence="tertiary"
              icon={SvgUserPlus}
              onClick={() => openModal(Modal.ACTIVATE)}
            >
              Activate User
            </Button>
            <Separator paddingXRem={0.5} />
            <Button
              prominence="tertiary"
              variant="danger"
              icon={SvgUserX}
              onClick={() => openModal(Modal.DELETE)}
            >
              Delete User
            </Button>
          </>
        );

      default: {
        const _exhaustive: never = user.status;
        return null;
      }
    }
  })();

  return (
    <>
      <Popover open={popoverOpen} onOpenChange={setPopoverOpen}>
        <Popover.Trigger asChild>
          <Button prominence="tertiary" icon={SvgMoreHorizontal} />
        </Popover.Trigger>
        <Popover.Content align="end" width="sm">
          <Section
            gap={0.5}
            height="auto"
            alignItems="stretch"
            justifyContent="start"
          >
            {actionButtons}
          </Section>
        </Popover.Content>
      </Popover>

      {modal === Modal.EDIT_GROUPS && user.id && (
        <EditUserModal
          user={user as UserRow & { id: string }}
          onClose={() => setModal(null)}
          onMutate={onMutate}
        />
      )}

      {modal === Modal.CANCEL_INVITE && (
        <ConfirmationModalLayout
          icon={(props) => (
            <SvgUserX {...props} className="text-action-danger-05" />
          )}
          title="Cancel Invite"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={() => {
                  handleAction(
                    () => cancelInvite(user.email),
                    "Invite cancelled"
                  );
                }}
              >
                Cancel Invite
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will no longer be able to join Onyx with this invite.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === Modal.DEACTIVATE && (
        <ConfirmationModalLayout
          icon={(props) => (
            <SvgUserX {...props} className="text-action-danger-05" />
          )}
          title="Deactivate User"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={async () => {
                  await handleAction(
                    () => deactivateUser(user.email),
                    "User deactivated"
                  );
                }}
              >
                Deactivate
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will immediately lose access to Onyx. Their sessions and agents will
            be preserved. Their license seat will be freed. You can reactivate
            this account later.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === Modal.ACTIVATE && (
        <ConfirmationModalLayout
          icon={SvgUserPlus}
          title="Activate User"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                onClick={async () => {
                  await handleAction(
                    () => activateUser(user.email),
                    "User activated"
                  );
                }}
              >
                Activate
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will regain access to Onyx.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === Modal.DELETE && (
        <ConfirmationModalLayout
          icon={(props) => (
            <SvgUserX {...props} className="text-action-danger-05" />
          )}
          title="Delete User"
          onClose={isSubmitting ? undefined : () => setModal(null)}
          submit={
            <Disabled disabled={isSubmitting}>
              <Button
                variant="danger"
                onClick={async () => {
                  await handleAction(
                    () => deleteUser(user.email),
                    "User deleted"
                  );
                }}
              >
                Delete
              </Button>
            </Disabled>
          }
        >
          <Text as="p" text03>
            <Text as="span" text05>
              {user.email}
            </Text>{" "}
            will be permanently removed from Onyx. All of their session history
            will be deleted. Deletion cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}

      {modal === Modal.RESET_PASSWORD && (
        <ConfirmationModalLayout
          icon={SvgKey}
          title={newPassword ? "Password Reset" : "Reset Password"}
          onClose={
            isSubmitting
              ? undefined
              : () => {
                  setModal(null);
                  setNewPassword(null);
                }
          }
          submit={
            newPassword ? (
              <Button
                onClick={() => {
                  setModal(null);
                  setNewPassword(null);
                }}
              >
                Done
              </Button>
            ) : (
              <Disabled disabled={isSubmitting}>
                <Button
                  variant="danger"
                  onClick={async () => {
                    setIsSubmitting(true);
                    try {
                      const result = await resetPassword(user.email);
                      setNewPassword(result.new_password);
                    } catch (err) {
                      toast.error(
                        err instanceof Error
                          ? err.message
                          : "Failed to reset password"
                      );
                    } finally {
                      setIsSubmitting(false);
                    }
                  }}
                >
                  Reset Password
                </Button>
              </Disabled>
            )
          }
        >
          {newPassword ? (
            <div className="flex flex-col gap-2">
              <Text as="p" text03>
                The password for{" "}
                <Text as="span" text05>
                  {user.email}
                </Text>{" "}
                has been reset. Copy the new password below — it will not be
                shown again.
              </Text>
              <code className="rounded-sm bg-background-neutral-02 px-3 py-2 text-sm select-all">
                {newPassword}
              </code>
            </div>
          ) : (
            <Text as="p" text03>
              This will generate a new random password for{" "}
              <Text as="span" text05>
                {user.email}
              </Text>
              . Their current password will stop working immediately.
            </Text>
          )}
        </ConfirmationModalLayout>
      )}
    </>
  );
}
