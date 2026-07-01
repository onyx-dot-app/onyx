"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { mutate } from "swr";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import useShareableUsers from "@/hooks/useShareableUsers";
import { toast } from "@/hooks/useToast";
import { useAgent } from "@/lib/agents/hooks";
import type { FullAgent, PersonaSharePermission } from "@/lib/agents/types";
import {
  removeSelfFromAgentShares,
  transferAgentOwnership,
  updateAgentShares,
} from "@/lib/agents/svc";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { MinimalUserSnapshot } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import Modal from "@/refresh-components/Modal";
import { Button, Divider, Text } from "@opal/components";
import {
  SvgArrowExchange,
  SvgArrowLeft,
  SvgEdit,
  SvgLink,
  SvgLock,
  SvgOrganization,
  SvgShare,
  SvgUser,
  SvgUserManage,
  SvgUsers,
} from "@opal/icons";
import { copyText, markdown } from "@opal/utils";
import { useModal } from "@/refresh-components/contexts/ModalContext";
import { AddPeoplePicker } from "@/sections/modals/AddPeoplePicker";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import {
  StaticPermissionLabel,
  TransferTrailingButton,
} from "@/sections/modals/ShareModalPermissionControls";
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

type ShareModalView = "share" | "transfer";

export type ShareDraftState = BaseShareDraftState<PersonaSharePermission>;

export interface ShareAgentModalProps {
  agentId?: number;
  /** Create-mode hydration: the full leveled draft from a prior open. */
  draftShares?: ShareDraftState | null;
  /** Create-mode save: receives the full leveled draft. */
  onDraftSave?: (draft: ShareDraftState) => void;
  groupIds?: number[];
  isFeatured?: boolean;
  isPublic?: boolean;
  labelIds?: number[];
  onShare?: (
    userIds: string[],
    groupIds: number[],
    isPublic: boolean,
    isFeatured: boolean,
    labelIds: number[]
  ) => Promise<void> | void;
  userIds?: string[];
}

function buildInitialDraftState(
  agent: FullAgent | null,
  props: ShareAgentModalProps
): ShareDraftState {
  if (agent) {
    return {
      groupShares: agent.group_shares,
      isPublic: agent.is_public,
      publicPermission: agent.public_permission,
      userShares: agent.user_shares,
    };
  }

  if (props.draftShares) {
    return props.draftShares;
  }

  // No saved agent and no create-mode draft. The legacy userIds/groupIds
  // props can't be hydrated into real users/groups synchronously here (the
  // user list loads async), so don't fabricate rows that would render UUIDs
  // as display names — start from an empty draft.
  return {
    groupShares: [],
    isPublic: props.isPublic ?? false,
    publicPermission: "VIEWER",
    userShares: [],
  };
}

async function refreshAgentShareCaches(agentId: number) {
  await Promise.all([
    mutate(SWR_KEYS.personas),
    mutate(SWR_KEYS.persona(agentId)),
    // Paginated admin list keys carry query params — match by prefix
    mutate(
      (key) => typeof key === "string" && key.startsWith(SWR_KEYS.adminAgents)
    ),
  ]);
}

export default function ShareAgentModal({
  agentId,
  draftShares = null,
  groupIds = [],
  isFeatured = false,
  isPublic = false,
  labelIds = [],
  onDraftSave,
  onShare,
  userIds = [],
}: ShareAgentModalProps) {
  const shareAgentModal = useModal();
  const { agent } = useAgent(agentId ?? null);
  const { data: shareableUsersData } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: transferableUsersData } = useShareableUsers({
    includeApiKeys: false,
  });
  const { data: shareableGroupsData } = useShareableGroups();
  const { isAdmin, user: currentUser } = useUser();
  const settings = useSettings();

  const shareableUsers = shareableUsersData ?? [];
  const transferableUsers = transferableUsersData ?? [];
  const shareableGroups = shareableGroupsData ?? [];
  const isPaidEnterpriseFeaturesEnabled =
    !settings.isLoading && settings.enterprise !== null;

  const initialValues = useMemo(
    () =>
      buildInitialDraftState(agent, {
        agentId,
        draftShares,
        groupIds,
        isFeatured,
        isPublic,
        labelIds,
        onShare,
        userIds,
      }),
    [
      agent,
      agentId,
      draftShares,
      groupIds,
      isFeatured,
      isPublic,
      labelIds,
      onShare,
      userIds,
    ]
  );

  const [draftState, setDraftState] = useState<ShareDraftState>(initialValues);
  const [modalInitialState, setModalInitialState] =
    useState<ShareDraftState>(initialValues);
  const [stagedUsers, setStagedUsers] = useState<MinimalUserSnapshot[]>([]);
  const [stagedGroups, setStagedGroups] = useState<MinimalUserGroupSnapshot[]>(
    []
  );
  const [stagedPermission, setStagedPermission] =
    useState<PersonaSharePermission>("VIEWER");
  const [transferTarget, setTransferTarget] =
    useState<TransferOwnershipTarget>(null);
  const [view, setView] = useState<ShareModalView>("share");
  const [isSaving, setIsSaving] = useState(false);
  const [isRemovingSelf, setIsRemovingSelf] = useState(false);
  const wasOpenRef = useRef(false);
  const hydratedFromAgentRef = useRef(false);

  useEffect(() => {
    if (shareAgentModal.isOpen && !wasOpenRef.current) {
      setView("share");
      setTransferTarget(null);
      setStagedUsers([]);
      setStagedGroups([]);
      setStagedPermission("VIEWER");
      hydratedFromAgentRef.current = false;

      if (!agentId || agent) {
        setDraftState(initialValues);
        setModalInitialState(initialValues);
        hydratedFromAgentRef.current = true;
      }
    }

    if (
      shareAgentModal.isOpen &&
      agentId &&
      agent &&
      !hydratedFromAgentRef.current
    ) {
      setDraftState(initialValues);
      setModalInitialState(initialValues);
      hydratedFromAgentRef.current = true;
    }

    if (!shareAgentModal.isOpen) {
      hydratedFromAgentRef.current = false;
    }

    wasOpenRef.current = shareAgentModal.isOpen;
  }, [agent, agentId, initialValues, shareAgentModal.isOpen]);

  const effectiveState = useMemo(
    () =>
      applyStagedShares(
        draftState,
        stagedUsers,
        stagedGroups,
        stagedPermission
      ),
    [draftState, stagedGroups, stagedPermission, stagedUsers]
  );

  const canEditShares = !agentId
    ? true
    : isAdmin ||
      agent?.user_permission === "OWNER" ||
      agent?.user_permission === "EDITOR";

  const canTransfer =
    !!agentId &&
    (agent?.user_permission === "OWNER" ||
      (isAdmin && agent?.ownership_vacant === true));

  const isDirty =
    serializeDraftState(effectiveState) !==
    serializeDraftState(modalInitialState);

  const existingUserIds = useMemo(
    () => new Set(draftState.userShares.map((share) => share.user.id)),
    [draftState.userShares]
  );
  const existingGroupIds = useMemo(
    () => new Set(draftState.groupShares.map((share) => share.group_id)),
    [draftState.groupShares]
  );

  const agentName = agent?.name ?? "Agent";

  const closeModal = useCallback(() => {
    setView("share");
    shareAgentModal.toggle(false);
  }, [shareAgentModal]);

  const updateUserSharePermission = useCallback(
    (userId: string, permission: PersonaSharePermission) => {
      // Staged entries live outside the draft under one default permission —
      // promote them into the draft so a per-row choice sticks
      const stagedUser = stagedUsers.find((user) => user.id === userId);
      if (stagedUser) {
        setStagedUsers((currentUsers) =>
          currentUsers.filter((user) => user.id !== userId)
        );
        setDraftState((currentDraftState) => ({
          ...currentDraftState,
          userShares: [
            ...currentDraftState.userShares.filter(
              (share) => share.user.id !== userId
            ),
            { permission, user: stagedUser },
          ],
        }));
        return;
      }
      setDraftState((currentDraftState) => ({
        ...currentDraftState,
        userShares: currentDraftState.userShares.map((share) =>
          share.user.id === userId ? { ...share, permission } : share
        ),
      }));
    },
    [stagedUsers]
  );

  const updateGroupSharePermission = useCallback(
    (groupId: number, permission: PersonaSharePermission) => {
      const stagedGroup = stagedGroups.find((group) => group.id === groupId);
      if (stagedGroup) {
        setStagedGroups((currentGroups) =>
          currentGroups.filter((group) => group.id !== groupId)
        );
        setDraftState((currentDraftState) => ({
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
        }));
        return;
      }
      setDraftState((currentDraftState) => ({
        ...currentDraftState,
        groupShares: currentDraftState.groupShares.map((share) =>
          share.group_id === groupId ? { ...share, permission } : share
        ),
      }));
    },
    [stagedGroups]
  );

  const removeUserShare = useCallback((userId: string) => {
    // Covers staged entries too — Remove Access on a not-yet-saved row
    setStagedUsers((currentUsers) =>
      currentUsers.filter((user) => user.id !== userId)
    );
    setDraftState((currentDraftState) => ({
      ...currentDraftState,
      userShares: currentDraftState.userShares.filter(
        (share) => share.user.id !== userId
      ),
    }));
  }, []);

  const removeGroupShare = useCallback((groupId: number) => {
    setStagedGroups((currentGroups) =>
      currentGroups.filter((group) => group.id !== groupId)
    );
    setDraftState((currentDraftState) => ({
      ...currentDraftState,
      groupShares: currentDraftState.groupShares.filter(
        (share) => share.group_id !== groupId
      ),
    }));
  }, []);

  const handleCopyLink = useCallback(async () => {
    if (!agentId) {
      return;
    }

    try {
      await copyText(`${window.location.origin}/app?agentId=${agentId}`);
      toast.success("Copied link.");
    } catch {
      toast.error("Failed to copy link.");
    }
  }, [agentId]);

  const handleSelfRemove = useCallback(async () => {
    // Create mode (no saved agent): mutate the local draft only.
    if (!agentId) {
      if (currentUser) {
        removeUserShare(currentUser.id);
      }
      closeModal();
      return;
    }
    // Saved agent but the current user hasn't loaded yet: don't no-op-and-close
    // (that would leave the share intact while signalling success).
    if (!currentUser) {
      return;
    }

    setIsRemovingSelf(true);
    const error = await removeSelfFromAgentShares(agentId);
    setIsRemovingSelf(false);

    if (error) {
      toast.error(error);
      return;
    }

    await refreshAgentShareCaches(agentId);
    toast.success("Access removed.");
    closeModal();
  }, [agentId, closeModal, currentUser, removeUserShare]);

  async function handleSave() {
    if (!isDirty) {
      closeModal();
      return;
    }

    setIsSaving(true);

    try {
      if (!agentId) {
        if (onDraftSave) {
          onDraftSave(effectiveState);
        } else {
          await onShare?.(
            effectiveState.userShares.map((share) => share.user.id),
            effectiveState.groupShares.map((share) => share.group_id),
            effectiveState.isPublic,
            isFeatured,
            labelIds
          );
        }
        closeModal();
        return;
      }

      const error = await updateAgentShares(
        agentId,
        {
          group_shares: effectiveState.groupShares
            .filter((share) => share.group_id !== agent?.owner_group?.id)
            .map((share) => ({
              group_id: share.group_id,
              permission: share.permission,
            })),
          is_public: effectiveState.isPublic,
          label_ids: labelIds.length > 0 ? labelIds : undefined,
          public_permission: effectiveState.publicPermission,
          user_shares: effectiveState.userShares
            .filter((share) => share.user.id !== agent?.owner?.id)
            .map((share) => ({
              permission: share.permission,
              user_id: share.user.id,
            })),
        },
        isPaidEnterpriseFeaturesEnabled
      );

      if (error) {
        toast.error(error);
        return;
      }

      await refreshAgentShareCaches(agentId);
      toast.success("Sharing updated.");
      closeModal();
    } finally {
      setIsSaving(false);
    }
  }

  async function handleTransfer() {
    if (!agentId || !transferTarget) {
      return;
    }

    setIsSaving(true);
    try {
      const error =
        transferTarget.type === "user"
          ? await transferAgentOwnership(agentId, {
              new_owner_user_id: transferTarget.value.replace("user-", ""),
            })
          : await transferAgentOwnership(agentId, {
              new_owner_group_id: Number(
                transferTarget.value.replace("group-", "")
              ),
            });

      if (error) {
        toast.error(error);
        return;
      }

      await refreshAgentShareCaches(agentId);
      toast.success("Ownership transferred.");
      closeModal();
    } finally {
      setIsSaving(false);
    }
  }

  function renderShareRows() {
    // Mock's three-state status icon: public → organization, anything shared
    // (rows or group ownership) → users, otherwise lock
    const hasAnyShare =
      effectiveState.userShares.length > 0 ||
      effectiveState.groupShares.length > 0 ||
      Boolean(agent?.owner_group);
    const scopeIcon = effectiveState.isPublic
      ? SvgOrganization
      : hasAnyShare
        ? SvgUsers
        : SvgLock;

    // The picker + status row + people table sit on a white plate over the
    // modal's tinted body, per the mock
    return (
      <div className="flex w-full flex-col gap-2 rounded-12 bg-background-tint-00 p-1">
        {canEditShares ? (
          <AddPeoplePicker
            existingGroupIds={existingGroupIds}
            existingUserIds={existingUserIds}
            groups={shareableGroups}
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
            users={shareableUsers}
          />
        ) : null}

        {/* Mock anatomy: icon + scope trigger on the left, org-permission
            trigger on the right — no label or description text */}
        <ShareAccessRow
          icon={scopeIcon}
          titleSlot={
            <SharePermissionMenu
              ariaLabel="Change sharing scope"
              disabled={!canEditShares}
              menuWidth="2xl"
              showTriggerIcon={false}
              onChange={(scope) => {
                setDraftState((currentDraftState) => ({
                  ...currentDraftState,
                  isPublic: scope === "PUBLIC",
                }));
              }}
              options={SCOPE_OPTIONS}
              value={effectiveState.isPublic ? "PUBLIC" : "PRIVATE"}
            />
          }
          rightChildren={
            <SharePermissionMenu
              ariaLabel="Change public permission"
              disabled={!canEditShares}
              onChange={(permission) => {
                setDraftState((currentDraftState) => ({
                  ...currentDraftState,
                  publicPermission: permission,
                }));
              }}
              options={PERMISSION_OPTIONS}
              value={effectiveState.publicPermission}
            />
          }
        />

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        {/* Admins always appear and always hold edit access (ENG-4175);
            on vacant agents this row carries the transfer affordance */}
        {agent ? (
          <ShareAccessRow
            description={`${agent.admin_count} user${
              agent.admin_count === 1 ? "" : "s"
            }`}
            icon={SvgUserManage}
            rightChildren={
              agent.ownership_vacant ? (
                <StaticPermissionLabel icon={SvgUserManage} label="Owner" />
              ) : (
                <StaticPermissionLabel icon={SvgEdit} label="Edit" muted />
              )
            }
            trailing={
              agent.ownership_vacant && canTransfer ? (
                <TransferTrailingButton
                  onTransfer={() => setView("transfer")}
                />
              ) : undefined
            }
            title="Admins"
          />
        ) : null}

        {agent?.owner ? (
          <ShareAccessRow
            avatarInitial={agent.owner.email.charAt(0).toUpperCase()}
            icon={SvgUser}
            rightChildren={
              <StaticPermissionLabel
                icon={SvgUserManage}
                label="Owner"
                muted={!canTransfer}
              />
            }
            trailing={
              canTransfer ? (
                <TransferTrailingButton
                  onTransfer={() => setView("transfer")}
                />
              ) : undefined
            }
            title={
              currentUser && agent.owner.id === currentUser.id
                ? `${agent.owner.email} (you)`
                : agent.owner.email
            }
          />
        ) : null}

        {agent?.owner_group ? (
          <ShareAccessRow
            avatarIcon={SvgUsers}
            icon={SvgUsers}
            rightChildren={
              <StaticPermissionLabel
                icon={SvgUserManage}
                label="Owner"
                muted={!canTransfer}
              />
            }
            trailing={
              canTransfer ? (
                <TransferTrailingButton
                  onTransfer={() => setView("transfer")}
                />
              ) : undefined
            }
            title={agent.owner_group.name}
          />
        ) : null}

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
                  disabled={!canEditShares && !isCurrentUser}
                  onChange={
                    canEditShares
                      ? (permission) =>
                          updateUserSharePermission(share.user.id, permission)
                      : undefined
                  }
                  onRemove={
                    isCurrentUser
                      ? handleSelfRemove
                      : canEditShares
                        ? () => removeUserShare(share.user.id)
                        : undefined
                  }
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
                onChange={
                  canEditShares
                    ? (permission) =>
                        updateGroupSharePermission(share.group_id, permission)
                    : undefined
                }
                onRemove={
                  canEditShares
                    ? () => removeGroupShare(share.group_id)
                    : undefined
                }
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

  return (
    <Modal open={shareAgentModal.isOpen} onOpenChange={shareAgentModal.toggle}>
      <Modal.Content height="lg" width={view === "transfer" ? "sm" : "md"}>
        <Modal.Header
          icon={view === "transfer" ? SvgArrowExchange : SvgShare}
          onClose={closeModal}
          title={
            view === "transfer"
              ? markdown(`Transfer *${agentName}*`)
              : markdown(`Share *${agentName}*`)
          }
        />

        <Modal.Body>
          {view === "transfer" ? (
            <TransferOwnershipView
              agent={agent}
              groups={shareableGroups}
              onSelectedTargetChange={setTransferTarget}
              selectedTarget={transferTarget}
              users={transferableUsers}
            />
          ) : agentId && !agent && hydratedFromAgentRef.current === false ? (
            <div className="flex w-full items-center justify-center py-6">
              <Text color="text-03" font="secondary-body">
                Loading sharing details...
              </Text>
            </div>
          ) : (
            renderShareRows()
          )}
        </Modal.Body>

        {/* Mock footer: Copy Link (share) / Back (transfer) pinned left,
            action group right; transfer's Cancel appears once a target is
            picked */}
        <Modal.Footer justifyContent="between">
          {view === "transfer" ? (
            <Button
              disabled={isSaving}
              icon={SvgArrowLeft}
              onClick={() => {
                setTransferTarget(null);
                setView("share");
              }}
              prominence="secondary"
            >
              Back
            </Button>
          ) : agentId ? (
            <Button
              icon={SvgLink}
              onClick={handleCopyLink}
              prominence="secondary"
            >
              Copy Link
            </Button>
          ) : (
            <span aria-hidden />
          )}

          <div className="flex items-center gap-2">
            {view === "transfer" ? (
              transferTarget ? (
                <Button
                  disabled={isSaving}
                  onClick={closeModal}
                  prominence="secondary"
                >
                  Cancel
                </Button>
              ) : null
            ) : (
              <Button
                disabled={isSaving || isRemovingSelf}
                onClick={closeModal}
                prominence="secondary"
              >
                {canEditShares ? "Cancel" : "Done"}
              </Button>
            )}
            {view === "transfer" ? (
              <Button
                disabled={!transferTarget || isSaving}
                onClick={handleTransfer}
              >
                Transfer
              </Button>
            ) : canEditShares ? (
              <Button
                disabled={!isDirty || isSaving || isRemovingSelf}
                onClick={handleSave}
              >
                Save
              </Button>
            ) : null}
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
