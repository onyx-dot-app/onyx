"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import useShareableUsers from "@/hooks/useShareableUsers";
import { toast } from "@/hooks/useToast";
import { useUser } from "@/providers/UserProvider";
import Modal from "@/refresh-components/Modal";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import { SharePermissionMenu } from "@/sections/modals/SharePermissionMenu";
import {
  PERMISSION_OPTIONS,
  SCOPE_OPTIONS,
} from "@/sections/modals/shareAccessConstants";
import {
  applyStagedShares,
  serializeDraftState,
  type ShareDraftState as BaseShareDraftState,
} from "@/sections/modals/shareDraftState";
import {
  TransferOwnershipTarget,
  TransferOwnershipView,
} from "@/sections/modals/TransferOwnershipView";
import {
  StaticPermissionLabel,
  TransferTrailingButton,
} from "@/sections/modals/ShareModalPermissionControls";
import { updateSkillShares, transferSkillOwnership } from "@/lib/skills/api";
import type { CustomSkill, SkillSharePermission } from "@/lib/skills/types";
import type { MinimalUserSnapshot } from "@/lib/types";
import { Button, Divider, Text } from "@opal/components";
import {
  SvgArrowExchange,
  SvgArrowLeft,
  SvgLock,
  SvgOrganization,
  SvgShare,
  SvgUser,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import { markdown } from "@opal/utils";

type ShareModalView = "share" | "transfer";

type SkillShareDraftState = BaseShareDraftState<SkillSharePermission>;

interface ShareSkillModalProps {
  skill: CustomSkill | null;
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
}

export default function ShareSkillModal({
  skill,
  open,
  onClose,
  onSaved,
}: ShareSkillModalProps) {
  const { data: shareableUsersData } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: transferableUsersData } = useShareableUsers({
    includeApiKeys: false,
  });
  const { data: shareableGroupsData } = useShareableGroups();
  const { isAdmin, user: currentUser } = useUser();

  const [draftState, setDraftState] = useState<SkillShareDraftState | null>(
    null
  );
  const [initialState, setInitialState] = useState<SkillShareDraftState | null>(
    null
  );
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [stagedPermission, setStagedPermission] =
    useState<SkillSharePermission>("VIEWER");
  const [transferTarget, setTransferTarget] =
    useState<TransferOwnershipTarget>(null);
  const [view, setView] = useState<ShareModalView>("share");
  const [saving, setSaving] = useState(false);
  const [hydratedSkillId, setHydratedSkillId] = useState<string | null>(null);

  // Hydrate once per open session: a background SWR refresh of `skill` must
  // not wipe in-progress staged edits.
  useEffect(() => {
    if (!open) {
      setHydratedSkillId(null);
      return;
    }
    if (!skill || skill.id === hydratedSkillId) return;
    const nextState: SkillShareDraftState = {
      groupShares: skill.group_shares,
      isPublic: skill.public_permission !== null,
      publicPermission: skill.public_permission ?? "VIEWER",
      userShares: skill.user_shares,
    };
    setDraftState(nextState);
    setInitialState(nextState);
    setStagedUsers([]);
    setStagedGroups([]);
    setStagedPermission("VIEWER");
    setTransferTarget(null);
    setView("share");
    setHydratedSkillId(skill.id);
  }, [open, skill, hydratedSkillId]);

  const effectiveState = useMemo(() => {
    if (!draftState) return null;
    return applyStagedShares(
      draftState,
      stagedUsers,
      stagedGroups,
      stagedPermission
    );
  }, [draftState, stagedGroups, stagedPermission, stagedUsers]);

  const canEditShares =
    skill?.user_permission === "OWNER" || skill?.user_permission === "EDITOR";
  const canEditOrgVisibility =
    skill?.user_permission === "OWNER" ||
    (isAdmin && skill?.user_permission === "EDITOR");
  const canTransfer =
    !!skill &&
    (skill.user_permission === "OWNER" || (isAdmin && skill.ownership_vacant));
  const isDirty =
    !!effectiveState &&
    !!initialState &&
    serializeDraftState(effectiveState) !== serializeDraftState(initialState);

  const existingUserIds = useMemo(() => {
    const ids = new Set(draftState?.userShares.map((share) => share.user.id));
    if (skill?.owner?.id) ids.add(skill.owner.id);
    return ids;
  }, [draftState?.userShares, skill?.owner?.id]);
  const existingGroupIds = useMemo(
    () => new Set(draftState?.groupShares.map((share) => share.group_id)),
    [draftState?.groupShares]
  );

  const closeModal = useCallback(() => {
    setView("share");
    onClose();
  }, [onClose]);

  const updateUserSharePermission = useCallback(
    (userId: string, permission: SkillSharePermission) => {
      const stagedUser = stagedUsers.find((user) => user.id === userId);
      if (stagedUser) {
        setStagedUsers((currentUsers) =>
          currentUsers.filter((user) => user.id !== userId)
        );
        setDraftState((currentDraftState) =>
          currentDraftState
            ? {
                ...currentDraftState,
                userShares: [
                  ...currentDraftState.userShares.filter(
                    (share) => share.user.id !== userId
                  ),
                  { permission, user: stagedUser },
                ],
              }
            : currentDraftState
        );
        return;
      }
      setDraftState((currentDraftState) =>
        currentDraftState
          ? {
              ...currentDraftState,
              userShares: currentDraftState.userShares.map((share) =>
                share.user.id === userId ? { ...share, permission } : share
              ),
            }
          : currentDraftState
      );
    },
    [stagedUsers]
  );

  const updateGroupSharePermission = useCallback(
    (groupId: number, permission: SkillSharePermission) => {
      const stagedGroup = stagedGroups.find((group) => group.id === groupId);
      if (stagedGroup) {
        setStagedGroups((currentGroups) =>
          currentGroups.filter((group) => group.id !== groupId)
        );
        setDraftState((currentDraftState) =>
          currentDraftState
            ? {
                ...currentDraftState,
                groupShares: [
                  ...currentDraftState.groupShares.filter(
                    (share) => share.group_id !== groupId
                  ),
                  {
                    group_id: stagedGroup.id,
                    group_name: stagedGroup.name,
                    permission,
                  },
                ],
              }
            : currentDraftState
        );
        return;
      }
      setDraftState((currentDraftState) =>
        currentDraftState
          ? {
              ...currentDraftState,
              groupShares: currentDraftState.groupShares.map((share) =>
                share.group_id === groupId ? { ...share, permission } : share
              ),
            }
          : currentDraftState
      );
    },
    [stagedGroups]
  );

  const removeUserShare = useCallback((userId: string) => {
    setStagedUsers((currentUsers) =>
      currentUsers.filter((user) => user.id !== userId)
    );
    setDraftState((currentDraftState) =>
      currentDraftState
        ? {
            ...currentDraftState,
            userShares: currentDraftState.userShares.filter(
              (share) => share.user.id !== userId
            ),
          }
        : currentDraftState
    );
  }, []);

  const removeGroupShare = useCallback((groupId: number) => {
    setStagedGroups((currentGroups) =>
      currentGroups.filter((group) => group.id !== groupId)
    );
    setDraftState((currentDraftState) =>
      currentDraftState
        ? {
            ...currentDraftState,
            groupShares: currentDraftState.groupShares.filter(
              (share) => share.group_id !== groupId
            ),
          }
        : currentDraftState
    );
  }, []);

  async function handleSave() {
    if (!skill || !effectiveState) return;
    if (!isDirty) {
      closeModal();
      return;
    }

    setSaving(true);
    try {
      await updateSkillShares(skill.id, {
        group_shares: effectiveState.groupShares.map((share) => ({
          group_id: share.group_id,
          permission: share.permission,
        })),
        public_permission: canEditOrgVisibility
          ? effectiveState.isPublic
            ? effectiveState.publicPermission
            : null
          : undefined,
        user_shares: effectiveState.userShares
          .filter((share) => share.user.id !== skill.owner?.id)
          .map((share) => ({
            permission: share.permission,
            user_id: share.user.id,
          })),
      });
      toast.success("Sharing updated.");
      onSaved();
      closeModal();
    } catch (err) {
      console.error("Failed to update skill sharing", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to update sharing"
      );
    } finally {
      setSaving(false);
    }
  }

  async function handleTransfer() {
    if (!skill || !transferTarget || transferTarget.type !== "user") return;

    setSaving(true);
    try {
      await transferSkillOwnership(skill.id, {
        new_owner_user_id: transferTarget.value.replace("user-", ""),
      });
      toast.success("Ownership transferred.");
      onSaved();
      closeModal();
    } catch (err) {
      console.error("Failed to transfer skill ownership", err);
      toast.error(
        err instanceof Error ? err.message : "Failed to transfer ownership"
      );
    } finally {
      setSaving(false);
    }
  }

  function renderShareRows() {
    if (!skill || !draftState || !effectiveState) return null;

    const hasAnyShare =
      effectiveState.userShares.length > 0 ||
      effectiveState.groupShares.length > 0;
    const scopeIcon = effectiveState.isPublic
      ? SvgOrganization
      : hasAnyShare
        ? SvgUsers
        : SvgLock;

    return (
      <div className="flex w-full flex-col gap-2 rounded-12 bg-background-tint-00 p-1">
        {canEditShares ? (
          <AddPeoplePicker
            existingGroupIds={existingGroupIds}
            existingUserIds={existingUserIds}
            groups={shareableGroupsData ?? []}
            onAddGroup={(group) => {
              setStagedGroups((currentGroups) => [...currentGroups, group]);
            }}
            onAddUser={(user) => {
              setStagedUsers((currentUsers) => [...currentUsers, user]);
            }}
            onRemoveGroup={(groupId) => {
              setStagedGroups((currentGroups) =>
                currentGroups.filter((group) => group.id !== groupId)
              );
            }}
            onRemoveUser={(userId) => {
              setStagedUsers((currentUsers) =>
                currentUsers.filter((user) => user.id !== userId)
              );
            }}
            onStagedPermissionChange={setStagedPermission}
            stagedGroups={stagedGroups}
            stagedPermission={stagedPermission}
            stagedUsers={stagedUsers}
            users={shareableUsersData ?? []}
          />
        ) : null}

        <ShareAccessRow
          icon={scopeIcon}
          titleSlot={
            <SharePermissionMenu
              ariaLabel="Change sharing scope"
              disabled={!canEditOrgVisibility}
              menuWidth="2xl"
              onChange={(scope) => {
                setDraftState((currentDraftState) =>
                  currentDraftState
                    ? { ...currentDraftState, isPublic: scope === "PUBLIC" }
                    : currentDraftState
                );
              }}
              options={SCOPE_OPTIONS}
              showTriggerIcon={false}
              value={effectiveState.isPublic ? "PUBLIC" : "PRIVATE"}
            />
          }
          rightChildren={
            <SharePermissionMenu
              ariaLabel="Change organization permission"
              disabled={!canEditOrgVisibility}
              onChange={(permission) => {
                setDraftState((currentDraftState) =>
                  currentDraftState
                    ? { ...currentDraftState, publicPermission: permission }
                    : currentDraftState
                );
              }}
              options={PERMISSION_OPTIONS}
              value={effectiveState.publicPermission}
            />
          }
        />

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        {skill.owner ? (
          <ShareAccessRow
            avatarInitial={skill.owner.email.charAt(0).toUpperCase()}
            icon={SvgUser}
            rightChildren={
              <StaticPermissionLabel
                icon={SvgUserManage}
                label="Owner"
                muted={!canTransfer}
              />
            }
            title={
              currentUser && skill.owner.id === currentUser.id
                ? `${skill.owner.email} (you)`
                : skill.owner.email
            }
            trailing={
              canTransfer ? (
                <TransferTrailingButton
                  onTransfer={() => setView("transfer")}
                />
              ) : undefined
            }
          />
        ) : (
          <ShareAccessRow
            icon={SvgUserManage}
            rightChildren={
              <StaticPermissionLabel icon={SvgUserManage} label="Owner" />
            }
            title="No active owner"
            trailing={
              canTransfer ? (
                <TransferTrailingButton
                  onTransfer={() => setView("transfer")}
                />
              ) : undefined
            }
          />
        )}

        {effectiveState.userShares.map((share) => {
          const isCurrentUser = currentUser?.id === share.user.id;
          return (
            <ShareAccessRow
              avatarInitial={share.user.email.charAt(0).toUpperCase()}
              icon={SvgUser}
              key={share.user.id}
              rightChildren={
                <SharePermissionMenu
                  ariaLabel={`Update access for ${share.user.email}`}
                  disabled={!canEditShares}
                  onChange={(permission) =>
                    updateUserSharePermission(share.user.id, permission)
                  }
                  onRemove={() => removeUserShare(share.user.id)}
                  options={PERMISSION_OPTIONS}
                  value={share.permission}
                />
              }
              title={
                isCurrentUser ? `${share.user.email} (you)` : share.user.email
              }
            />
          );
        })}

        {effectiveState.groupShares.map((share) => (
          <ShareAccessRow
            avatarIcon={SvgUsers}
            icon={SvgUsers}
            key={share.group_id}
            rightChildren={
              <SharePermissionMenu
                ariaLabel={`Update access for ${share.group_name}`}
                disabled={!canEditShares}
                onChange={(permission) =>
                  updateGroupSharePermission(share.group_id, permission)
                }
                onRemove={() => removeGroupShare(share.group_id)}
                options={PERMISSION_OPTIONS}
                value={share.permission}
              />
            }
            title={share.group_name}
          />
        ))}
      </div>
    );
  }

  if (!skill) return null;

  return (
    <Modal open={open} onOpenChange={(isOpen) => !isOpen && closeModal()}>
      <Modal.Content height="lg" width={view === "transfer" ? "sm" : "md"}>
        <Modal.Header
          icon={view === "transfer" ? SvgArrowExchange : SvgShare}
          title={
            view === "transfer"
              ? markdown(`Transfer *${skill.name}*`)
              : markdown(`Share *${skill.name}*`)
          }
          onClose={closeModal}
        />
        <Modal.Body>
          {view === "transfer" ? (
            <TransferOwnershipView
              agent={{ owner: skill.owner, owner_group: null }}
              groups={[]}
              onSelectedTargetChange={setTransferTarget}
              selectedTarget={transferTarget}
              users={transferableUsersData ?? []}
            />
          ) : !draftState ? (
            <div className="flex w-full items-center justify-center py-6">
              <Text color="text-03" font="secondary-body">
                Loading sharing details...
              </Text>
            </div>
          ) : (
            renderShareRows()
          )}
        </Modal.Body>
        <Modal.Footer justifyContent="between">
          {view === "transfer" ? (
            <Button
              disabled={saving}
              icon={SvgArrowLeft}
              onClick={() => {
                setTransferTarget(null);
                setView("share");
              }}
              prominence="secondary"
            >
              Back
            </Button>
          ) : (
            <span aria-hidden />
          )}

          <div className="flex items-center gap-2">
            <Button
              disabled={saving}
              onClick={closeModal}
              prominence="secondary"
            >
              {canEditShares || view === "transfer" ? "Cancel" : "Done"}
            </Button>
            {view === "transfer" ? (
              <Button
                disabled={
                  !transferTarget || transferTarget.type !== "user" || saving
                }
                onClick={handleTransfer}
              >
                Transfer
              </Button>
            ) : canEditShares ? (
              <Button disabled={!isDirty || saving} onClick={handleSave}>
                Save
              </Button>
            ) : null}
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
