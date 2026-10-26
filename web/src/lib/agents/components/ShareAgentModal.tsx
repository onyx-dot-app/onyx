"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { mutate } from "swr";
import useShareableGroups, {
  type MinimalUserGroupSnapshot,
} from "@/hooks/useShareableGroups";
import useShareableUsers from "@/hooks/useShareableUsers";
import { Content, InputPadder, Section, toast } from "@opal/layouts";
import { useAgent } from "@/lib/agents/hooks";
import type { FullAgent, PersonaSharePermission } from "@/lib/agents/types";
import {
  removeSelfFromAgentShares,
  transferAgentOwnership,
  updateAgentShares,
} from "@/lib/agents/svc";
import { SWR_KEYS } from "@/lib/swr-keys";
import { Permission, type MinimalUserSnapshot } from "@/lib/types";
import { hasPermission } from "@/lib/permissions/utils";
import { can } from "@/lib/permissions/resource-actions";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { Modal } from "@opal/components";
import {
  Button,
  Card,
  Divider,
  InputMultiComboBox,
  Table,
  Text,
  type SelectOption,
  type TableColumn,
  type TagItem,
} from "@opal/components";
import type { IconFunctionComponent } from "@opal/types";
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
import { copyText, escapeMarkdown, markdown } from "@opal/utils";
import { useModal } from "@opal/components";
import { ShareAccessRow } from "@/sections/modals/ShareAccessRow";
import {
  StaticPermissionLabel,
  TransferTrailingButton,
} from "@/sections/modals/ShareModalPermissionControls";
import { SharePermissionMenu } from "@/lib/permissions/components";
import {
  useSharePermissionOptions,
  useShareScopeOptions,
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

/** One row of the people table: the admins, an owner, or a share. */
interface ShareTableRow {
  id: string;
  name: string;
  description?: string;
  icon: IconFunctionComponent;
  trailing: React.ReactNode;
}

// Picker option values carry the share kind, since user and group ids overlap.
const USER_OPTION_PREFIX = "user:";
const GROUP_OPTION_PREFIX = "group:";

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
    mutate(SWR_KEYS.agents),
    mutate(SWR_KEYS.agent(agentId)),
    // Paginated admin list keys carry query params — match by prefix
    mutate(
      (key) => typeof key === "string" && key.startsWith(SWR_KEYS.adminAgents)
    ),
  ]);
}

export function ShareAgentModal({
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
  const t = useTranslations("agents.modals");
  const tShare = useTranslations("chat.modals.share");
  const shareAgentModal = useModal();
  const permissionOptions = useSharePermissionOptions();
  const scopeOptions = useShareScopeOptions();
  const { agent, refresh: refreshAgent } = useAgent(agentId ?? null);
  const { data: shareableUsersData } = useShareableUsers({
    includeApiKeys: true,
  });
  const { data: transferableUsersData } = useShareableUsers({
    includeApiKeys: false,
  });
  const { data: shareableGroupsData } = useShareableGroups();
  const { isAdmin, user: currentUser, adminCapabilities } = useUser();
  const settings = useSettings();

  const shareableUsers = shareableUsersData ?? [];
  const transferableUsers = transferableUsersData ?? [];
  const shareableGroups = shareableGroupsData ?? [];

  // Publish is owner-or-admin per agent, so use the server's answer, not a role check.
  // A new agent has nothing stamped yet, and its creator owns it, so publish stays open.
  const canPublish = !agentId || can(agent, "publish");
  // Attaching an agent to a group is a MANAGE_AGENTS action (decision D7), so a plain
  // owner can share with users but not with groups.
  const canGroupShare = hasPermission(
    adminCapabilities,
    Permission.MANAGE_AGENTS
  );
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
  const [query, setQuery] = useState("");
  const [transferTarget, setTransferTarget] =
    useState<TransferOwnershipTarget>(null);
  const [view, setView] = useState<ShareModalView>("share");
  const [isSaving, setIsSaving] = useState(false);
  const [isRemovingSelf, setIsRemovingSelf] = useState(false);
  const wasOpenRef = useRef(false);
  const hydratedFromAgentRef = useRef(false);
  const [isRefreshingAgent, setIsRefreshingAgent] = useState(false);

  useEffect(() => {
    if (shareAgentModal.isOpen && !wasOpenRef.current) {
      setView("share");
      setTransferTarget(null);
      setStagedUsers([]);
      setStagedGroups([]);
      setQuery("");
      hydratedFromAgentRef.current = false;

      if (!agentId) {
        setDraftState(initialValues);
        setModalInitialState(initialValues);
        hydratedFromAgentRef.current = true;
      } else {
        // useAgent turns off SWR revalidation, so owner and share state changed
        // elsewhere would be stale here. Refetch on open before hydrating. The
        // rows stay behind the loading state until then, and a failed refetch
        // falls back to the cached snapshot.
        setIsRefreshingAgent(true);
        void refreshAgent().finally(() => setIsRefreshingAgent(false));
        wasOpenRef.current = true;
        return;
      }
    }

    if (
      shareAgentModal.isOpen &&
      agentId &&
      agent &&
      !isRefreshingAgent &&
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
  }, [
    agent,
    agentId,
    initialValues,
    isRefreshingAgent,
    refreshAgent,
    shareAgentModal.isOpen,
  ]);

  const effectiveState = useMemo(
    () =>
      // New picks join as viewers; each row's menu changes that
      applyStagedShares(draftState, stagedUsers, stagedGroups, "VIEWER"),
    [draftState, stagedGroups, stagedUsers]
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

  const agentName = agent?.name ?? t("shareAgent.agentFallback.name");

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
      toast.success(t("shareAgent.toasts.linkCopied"));
    } catch {
      toast.error(t("shareAgent.toasts.copyLinkFailed"));
    }
  }, [agentId, t]);

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
    toast.success(t("shareAgent.toasts.accessRemoved"));
    closeModal();
  }, [agentId, closeModal, currentUser, removeUserShare, t]);

  function pickShareOption(value: string) {
    if (value.startsWith(USER_OPTION_PREFIX)) {
      const userId = value.slice(USER_OPTION_PREFIX.length);
      const user = shareableUsers.find((candidate) => candidate.id === userId);
      if (user) {
        setStagedUsers((currentUsers) => [...currentUsers, user]);
      }
      return;
    }
    const groupId = Number(value.slice(GROUP_OPTION_PREFIX.length));
    const group = shareableGroups.find((candidate) => candidate.id === groupId);
    if (group) {
      setStagedGroups((currentGroups) => [...currentGroups, group]);
    }
  }

  // Picking a shared row again in the search removes its access, like the
  // row's own Remove action
  function unpickShareOption(value: string) {
    if (value.startsWith(USER_OPTION_PREFIX)) {
      const userId = value.slice(USER_OPTION_PREFIX.length);
      if (userId === currentUser?.id) {
        void handleSelfRemove();
        return;
      }
      removeUserShare(userId);
      return;
    }
    removeGroupShare(Number(value.slice(GROUP_OPTION_PREFIX.length)));
  }

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
      toast.success(t("shareAgent.toasts.sharingUpdated"));
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
      toast.success(t("shareAgent.toasts.ownershipTransferred"));
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

    const shareOptions: SelectOption[] = [
      ...shareableUsers.map((user) => ({
        value: `${USER_OPTION_PREFIX}${user.id}`,
        title: user.email,
        icon: SvgUser,
      })),
      ...(canGroupShare
        ? shareableGroups.map((group) => ({
            value: `${GROUP_OPTION_PREFIX}${group.id}`,
            title: group.name,
            icon: SvgUsers,
          }))
        : []),
    ];
    // Shared people show as selected options; the table lists them
    const pickedTags: TagItem[] = [
      ...effectiveState.userShares.map((share) => ({
        id: `${USER_OPTION_PREFIX}${share.user.id}`,
        label: share.user.email,
      })),
      ...effectiveState.groupShares.map((share) => ({
        id: `${GROUP_OPTION_PREFIX}${share.group_id}`,
        label: share.group_name,
      })),
    ];

    const transferButton = canTransfer ? (
      <TransferTrailingButton onTransfer={() => setView("transfer")} />
    ) : null;
    const ownerLabel = (
      <Section
        flexDirection="row"
        justifyContent="end"
        alignItems="center"
        gap={1}
        width="fit"
      >
        <StaticPermissionLabel
          icon={SvgUserManage}
          label={t("shareAgent.permission.owner.label")}
          muted={!canTransfer}
        />
        {transferButton}
      </Section>
    );

    const tableRows: ShareTableRow[] = [];
    // Admins always appear and always hold edit access (ENG-4175); on vacant
    // agents this row carries the transfer affordance
    if (agent) {
      tableRows.push({
        id: "admins",
        name: t("shareAgent.admins.title"),
        description: t("shareAgent.admins.description", {
          count: agent.admin_count,
        }),
        icon: SvgUserManage,
        trailing: agent.ownership_vacant ? (
          ownerLabel
        ) : (
          <StaticPermissionLabel
            icon={SvgEdit}
            label={t("shareAgent.permission.edit.label")}
            muted
          />
        ),
      });
    }
    if (agent?.owner) {
      tableRows.push({
        id: "owner",
        name:
          currentUser && agent.owner.id === currentUser.id
            ? t("shareAgent.row.you.title", { email: agent.owner.email })
            : agent.owner.email,
        icon: SvgUser,
        trailing: ownerLabel,
      });
    }
    if (agent?.owner_group) {
      tableRows.push({
        id: "owner-group",
        name: agent.owner_group.name,
        icon: SvgUsers,
        trailing: ownerLabel,
      });
    }
    for (const share of effectiveState.userShares) {
      const isCurrentUser = currentUser?.id === share.user.id;
      tableRows.push({
        id: `${USER_OPTION_PREFIX}${share.user.id}`,
        name: isCurrentUser
          ? t("shareAgent.row.you.title", { email: share.user.email })
          : share.user.email,
        icon: SvgUser,
        trailing: (
          <SharePermissionMenu
            ariaLabel={t("shareAgent.row.updateAccess.ariaLabel", {
              name: share.user.email,
            })}
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
            options={permissionOptions}
            value={share.permission}
          />
        ),
      });
    }
    for (const share of effectiveState.groupShares) {
      tableRows.push({
        id: `${GROUP_OPTION_PREFIX}${share.group_id}`,
        name: share.group_name,
        icon: SvgUsers,
        trailing: (
          <SharePermissionMenu
            ariaLabel={t("shareAgent.row.updateAccess.ariaLabel", {
              name: share.group_name,
            })}
            disabled={!canEditShares}
            onChange={
              canEditShares
                ? (permission) =>
                    updateGroupSharePermission(share.group_id, permission)
                : undefined
            }
            onRemove={
              canEditShares ? () => removeGroupShare(share.group_id) : undefined
            }
            options={permissionOptions}
            value={share.permission}
          />
        ),
      });
    }

    const columns: TableColumn<ShareTableRow>[] = [
      {
        kind: "qualifier",
        content: "icon",
        icon: (row) => row.icon,
        background: true,
      },
      {
        kind: "data",
        field: "name",
        title: t("shareAgent.people.label"),
        weight: 60,
        sortable: false,
        hideable: false,
        cell: (name, row) => (
          <Content
            title={name}
            description={row.description}
            sizePreset="main-ui"
            variant="section"
          />
        ),
      },
      {
        kind: "display",
        id: "access",
        width: { weight: 40 },
        hideable: false,
        alignment: "right",
        cell: (row) => row.trailing,
      },
    ];

    // The card adds 0.5rem and each row's own padding the other 0.5rem
    return (
      <Card padding={2}>
        <Section gap={2} height="auto" alignItems="stretch">
          {canEditShares ? (
            <InputMultiComboBox
              focusOnMount
              value={query}
              onChange={setQuery}
              onAdd={() => undefined}
              tags={pickedTags}
              showTags={false}
              options={shareOptions}
              onSelectOption={(option) => pickShareOption(option.value)}
              onRemoveTag={unpickShareOption}
              placeholder={tShare("addPeople.searchInput.placeholder")}
            />
          ) : null}

          {/* Mock anatomy: icon + scope trigger on the left, org-permission
            trigger on the right — no label or description text */}
          <ShareAccessRow
            icon={scopeIcon}
            titleSlot={
              <SharePermissionMenu
                ariaLabel={t("shareAgent.scopeMenu.ariaLabel")}
                // Stays visible so the current scope still reads; only changing it is gated.
                disabled={!canEditShares || !canPublish}
                showTriggerIcon={false}
                onChange={(scope) => {
                  setDraftState((currentDraftState) => ({
                    ...currentDraftState,
                    isPublic: scope === "PUBLIC",
                  }));
                }}
                options={scopeOptions}
                value={effectiveState.isPublic ? "PUBLIC" : "PRIVATE"}
              />
            }
            rightChildren={
              <SharePermissionMenu
                ariaLabel={t("shareAgent.publicPermissionMenu.ariaLabel")}
                disabled={!canEditShares || !canPublish}
                onChange={(permission) => {
                  setDraftState((currentDraftState) => ({
                    ...currentDraftState,
                    publicPermission: permission,
                  }));
                }}
                options={permissionOptions}
                value={effectiveState.publicPermission}
              />
            }
          />

          <Divider paddingParallel={0} paddingPerpendicular={0} />

          {tableRows.length > 0 ? (
            <Table
              label={t("shareAgent.people.label")}
              items={tableRows}
              columns={columns}
              getRowId={(row) => row.id}
              pageSize={false}
              prominence="secondary"
              header={false}
            />
          ) : null}
        </Section>
      </Card>
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
              ? markdown(
                  t("shareAgent.transfer.title", {
                    name: escapeMarkdown(agentName),
                  })
                )
              : markdown(
                  t("shareAgent.share.title", {
                    name: escapeMarkdown(agentName),
                  })
                )
          }
        />

        <Modal.Body padding={2}>
          {view === "transfer" ? (
            <InputPadder>
              <TransferOwnershipView
                agent={agent}
                // Handing an agent to a group attaches it to that group, so it answers to
                // MANAGE_AGENTS like group sharing does; transfer to a user stays open.
                groups={canGroupShare ? shareableGroups : []}
                onSelectedTargetChange={setTransferTarget}
                selectedTarget={transferTarget}
                users={transferableUsers}
              />
            </InputPadder>
          ) : agentId && !hydratedFromAgentRef.current ? (
            <InputPadder>
              <div className="flex w-full items-center justify-center py-6">
                <Text color="text-03" font="secondary-body">
                  {t("shareAgent.loading.description")}
                </Text>
              </div>
            </InputPadder>
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
              {t("shareAgent.back.label")}
            </Button>
          ) : agentId ? (
            <Button
              icon={SvgLink}
              onClick={handleCopyLink}
              prominence="secondary"
            >
              {t("shareAgent.copyLink.label")}
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
                  {t("shareAgent.cancel.label")}
                </Button>
              ) : null
            ) : (
              <Button
                disabled={isSaving || isRemovingSelf}
                onClick={closeModal}
                prominence="secondary"
              >
                {canEditShares
                  ? t("shareAgent.cancel.label")
                  : t("shareAgent.done.label")}
              </Button>
            )}
            {view === "transfer" ? (
              <Button
                disabled={!transferTarget || isSaving}
                onClick={handleTransfer}
              >
                {t("shareAgent.transfer.label")}
              </Button>
            ) : canEditShares ? (
              <Button
                disabled={!isDirty || isSaving || isRemovingSelf}
                onClick={handleSave}
              >
                {t("shareAgent.save.label")}
              </Button>
            ) : null}
          </div>
        </Modal.Footer>
      </Modal.Content>
    </Modal>
  );
}
