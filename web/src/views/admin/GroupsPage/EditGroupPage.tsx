"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import useGroupMemberCandidates from "./useGroupMemberCandidates";
import {
  Button,
  Card,
  Divider,
  MessageCard,
  Switch,
  Table,
} from "@opal/components";
import { IllustrationContent, InputHorizontal, toast } from "@opal/layouts";
import {
  SvgUsers,
  SvgTrash,
  SvgMinusCircle,
  SvgPlusCircle,
  SvgSimpleLoader,
  SvgUserShield,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import SvgNoResult from "@opal/illustrations/no-result";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { InputTypeIn } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { ConfirmationModalLayout } from "@opal/layouts";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import { AccountType } from "@/lib/types";
import type { SecuritySettings, UserGroup } from "@/lib/types";
import { useUser } from "@/providers/UserProvider";
import { useSettings } from "@/lib/settings/hooks";
import { Tier } from "@/lib/settings/types";
import { tierAtLeast } from "@/lib/tiers";
import type { MemberRow, TokenRateLimitDisplay } from "./interfaces";
import { makeBaseColumns, memberTableColumns, tc, PAGE_SIZE } from "./shared";
import {
  renameGroup,
  updateGroup,
  setGroupIncognito,
  deleteGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
  saveGroupPermissions,
  setGroupManager,
  refreshGroupLists,
} from "./svc";
import { SWR_KEYS } from "@/lib/swr-keys";
import SharedGroupResources from "@/views/admin/GroupsPage/SharedGroupResources";
import GroupPermissionsSection from "./GroupPermissionsSection";
import TokenLimitSection from "./TokenLimitSection";
import type { TokenLimit } from "./TokenLimitSection";
import { can } from "@/lib/permissions/resource-actions";

const HOURS_PER_DAY = 24;
const addModeColumns = memberTableColumns;

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface EditGroupPageProps {
  groupId: number;
}

function EditGroupPage({ groupId }: EditGroupPageProps) {
  const router = useRouter();
  const { mutate } = useSWRConfig();
  const settings = useSettings();
  const { user } = useUser();
  const currentUserId = user?.id;
  const isEnterpriseTier = tierAtLeast(settings.tier, Tier.ENTERPRISE);
  const tokenLimitsDisabledTooltip = markdown(
    "Token rate limits are available on the [Enterprise version of Onyx](/admin/billing) only."
  );

  // Fetch the group data — poll every 5s while syncing so the UI updates
  // automatically when the backend finishes processing the previous edit.
  const {
    data: groups,
    isLoading: groupLoading,
    error: groupError,
  } = useSWR<UserGroup[]>(
    SWR_KEYS.adminUserGroupsWithDefault,
    errorHandlingFetcher,
    {
      refreshInterval: (latestData) => {
        const g = latestData?.find((g) => g.id === groupId);
        return g && !g.is_up_to_date ? 5000 : 0;
      },
    }
  );

  const group = useMemo(
    () => groups?.find((g) => g.id === groupId) ?? null,
    [groups, groupId]
  );

  const canManage = can(group, "manage");
  const canManageMembers = can(group, "manage_members");
  const canDelete = can(group, "delete");
  const canEditPermissions = can(group, "edit_permissions");
  const canEditTokenLimits = can(group, "edit_token_limits");
  const isDefaultGroup = group?.is_default ?? false;

  const isSyncing = group != null && !group.is_up_to_date;

  // Gate on edit_token_limits so a non-manager (who'd 403 on the read) skips the fetch.
  // Skip retry on tier-gated 402 so SWR doesn't churn isLoading.
  const { data: tokenRateLimits, isLoading: tokenLimitsLoading } = useSWR<
    TokenRateLimitDisplay[]
  >(
    canEditTokenLimits ? SWR_KEYS.userGroupTokenRateLimit(groupId) : null,
    errorHandlingFetcher,
    { onErrorRetry: skipRetryOnAuthError }
  );

  // Fetch permissions for this group (admin only)
  const { data: groupPermissions, isLoading: permissionsLoading } = useSWR<
    string[]
  >(
    canEditPermissions ? SWR_KEYS.userGroupPermissions(groupId) : null,
    errorHandlingFetcher
  );

  // The flag only does anything under designated-groups availability, so the
  // field stays off the page entirely elsewhere. Curators get a 403 reading
  // security settings, which also leaves it hidden.
  const { data: securitySettings } = useSWR<
    Pick<SecuritySettings, "incognito_availability">
  >(SWR_KEYS.adminSecuritySettings, errorHandlingFetcher, {
    onErrorRetry: skipRetryOnAuthError,
  });
  const showIncognitoField =
    securitySettings?.incognito_availability === "groups";

  // Form state
  const [groupName, setGroupName] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const isSubmittingRef = useRef(false);
  const [selectedCcPairIds, setSelectedCcPairIds] = useState<number[]>([]);
  const [selectedDocSetIds, setSelectedDocSetIds] = useState<number[]>([]);
  const [selectedAgentIds, setSelectedAgentIds] = useState<number[]>([]);
  const [tokenLimits, setTokenLimits] = useState<TokenLimit[]>([
    {
      tokenId: null,
      enabled: true,
      tokenBudget: null,
      periodDays: null,
      costBudgetDollars: null,
    },
  ]);
  const [enabledPermissions, setEnabledPermissions] = useState<Set<string>>(
    new Set()
  );
  const [incognitoEnabled, setIncognitoEnabled] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [isAddingMembers, setIsAddingMembers] = useState(false);
  const initialAgentIdsRef = useRef<number[]>([]);
  const initialDocSetIdsRef = useRef<number[]>([]);

  // Users + service accounts (curator-accessible — see hook docs).
  const {
    rows: allRows,
    isLoading: candidatesLoading,
    error: candidatesError,
  } = useGroupMemberCandidates();

  const isLoading =
    groupLoading ||
    candidatesLoading ||
    tokenLimitsLoading ||
    permissionsLoading;
  const error = groupError ?? candidatesError;

  // Pre-populate form when group data loads
  useEffect(() => {
    if (group && !initialized) {
      setGroupName(group.name);
      setSelectedUserIds(group.users.map((u) => u.id));
      setSelectedCcPairIds(group.cc_pairs.map((cc) => cc.id));
      const docSetIds = group.document_sets.map((ds) => ds.id);
      setSelectedDocSetIds(docSetIds);
      initialDocSetIdsRef.current = docSetIds;
      const agentIds = group.personas.map((p) => p.id);
      setSelectedAgentIds(agentIds);
      initialAgentIdsRef.current = agentIds;
      setIncognitoEnabled(group.incognito_enabled);
      setInitialized(true);
    }
  }, [group, initialized]);

  // Pre-populate token limits once. Re-seeding on later revalidations (focus,
  // reconnect, a concurrent edit) would silently discard unsaved edits.
  const tokenLimitsSeededRef = useRef(false);
  useEffect(() => {
    if (!tokenRateLimits || tokenLimitsSeededRef.current) return;
    tokenLimitsSeededRef.current = true;
    // No saved limits — keep the blank starter row.
    if (tokenRateLimits.length === 0) return;
    setTokenLimits(
      tokenRateLimits.map((trl) => ({
        tokenId: trl.token_id,
        enabled: trl.enabled,
        tokenBudget: trl.token_budget,
        periodDays: trl.period_hours / HOURS_PER_DAY,
        costBudgetDollars:
          trl.cost_budget_cents != null ? trl.cost_budget_cents / 100 : null,
      }))
    );
  }, [tokenRateLimits]);

  // Pre-populate permissions once. Re-seeding on later revalidations (focus,
  // reconnect, a concurrent edit) would silently discard unsaved toggles.
  const permissionsSeededRef = useRef(false);
  useEffect(() => {
    if (groupPermissions && !permissionsSeededRef.current) {
      permissionsSeededRef.current = true;
      setEnabledPermissions(new Set(groupPermissions));
    }
  }, [groupPermissions]);

  const memberRows = useMemo(() => {
    const selected = new Set(selectedUserIds);
    return allRows.filter((r) => selected.has(r.id ?? r.email));
  }, [allRows, selectedUserIds]);

  const currentRowSelection = useMemo(() => {
    const sel: Record<string, boolean> = {};
    for (const id of selectedUserIds) sel[id] = true;
    return sel;
  }, [selectedUserIds]);

  const handleRemoveMember = useCallback((userId: string) => {
    setSelectedUserIds((prev) => prev.filter((id) => id !== userId));
  }, []);

  const managerIds = useMemo(() => new Set(group?.manager_ids ?? []), [group]);
  // Manager must be a saved member (can't assign one that isn't persisted yet).
  const persistedMemberIds = useMemo(
    () => new Set(group?.users.map((u) => u.id) ?? []),
    [group]
  );
  const [pendingManagerIds, setPendingManagerIds] = useState<Set<string>>(
    () => new Set()
  );

  const isOwnManagerRow = useCallback(
    (userId: string) =>
      currentUserId != null &&
      userId === currentUserId &&
      (managerIds.has(userId) || pendingManagerIds.has(userId)),
    [currentUserId, managerIds, pendingManagerIds]
  );

  // Mirrors the backend guard. Persisted only — dropping an unsaved add strands nobody.
  const isLastGroupMember = useCallback(
    (row: MemberRow) =>
      row.account_type === AccountType.STANDARD &&
      persistedMemberIds.has(row.id ?? row.email) &&
      row.groups.length <= 1,
    [persistedMemberIds]
  );

  // Hits its endpoint immediately (member add/remove defers to Save), then revalidates.
  const handleToggleManager = useCallback(
    async (userId: string, makeManager: boolean) => {
      setPendingManagerIds((prev) => new Set(prev).add(userId));
      try {
        await setGroupManager(groupId, userId, makeManager);
        await refreshGroupLists(mutate);
        toast.success(makeManager ? "Manager assigned" : "Manager revoked");
      } catch (err) {
        console.error("Failed to update manager:", err);
        toast.error(
          err instanceof Error ? err.message : "Failed to update manager"
        );
      } finally {
        setPendingManagerIds((prev) => {
          const next = new Set(prev);
          next.delete(userId);
          return next;
        });
      }
    },
    [groupId, mutate]
  );

  const memberColumns = useMemo(
    () => [
      ...makeBaseColumns((row) => managerIds.has(row.id ?? row.email)),
      tc.actions({
        showSorting: false,
        showColumnVisibility: false,
        cell: (row: MemberRow) => {
          if (!canManageMembers) return null;
          const userId = row.id ?? row.email;
          const isManager = managerIds.has(userId);
          const isPersisted = persistedMemberIds.has(userId);
          const isPending = pendingManagerIds.has(userId);
          const isOwnManager = isOwnManagerRow(userId);
          const isLastGroup = isLastGroupMember(row);
          return (
            <div className="flex items-center gap-1">
              {canManage && (
                <Button
                  icon={isPending ? SvgSimpleLoader : SvgUserShield}
                  prominence="tertiary"
                  interaction={isManager ? "hover" : "rest"}
                  disabled={!isPersisted || isPending || isOwnManager}
                  aria-label={isManager ? "Revoke manager" : "Make manager"}
                  tooltip={
                    !isPersisted
                      ? "Save the group before assigning a manager"
                      : isOwnManager
                        ? "You can't revoke your own manager access"
                        : isManager
                          ? "Revoke manager"
                          : "Make manager"
                  }
                  onClick={(e) => {
                    e.stopPropagation();
                    handleToggleManager(userId, !isManager);
                  }}
                />
              )}
              <Button
                icon={SvgMinusCircle}
                prominence="tertiary"
                disabled={isOwnManager || isLastGroup}
                aria-label="Remove member"
                tooltip={
                  isOwnManager
                    ? "You can't remove yourself while managing this group"
                    : isLastGroup
                      ? "This is their only group. Add them to another group first."
                      : undefined
                }
                onClick={(e) => {
                  e.stopPropagation();
                  handleRemoveMember(userId);
                }}
              />
            </div>
          );
        },
      }),
    ],
    [
      handleRemoveMember,
      handleToggleManager,
      isLastGroupMember,
      isOwnManagerRow,
      managerIds,
      persistedMemberIds,
      pendingManagerIds,
      canManage,
      canManageMembers,
    ]
  );

  // IDs of members not visible in the add-mode table (e.g. inactive users).
  // We preserve these so they aren't silently removed when the table fires
  // onSelectionChange with only the visible rows.
  const hiddenMemberIds = useMemo(() => {
    const visibleIds = new Set(allRows.map((r) => r.id ?? r.email));
    return selectedUserIds.filter((id) => !visibleIds.has(id));
  }, [allRows, selectedUserIds]);

  // Guard onSelectionChange: ignore updates until the form is fully initialized.
  // Without this, TanStack fires onSelectionChange before all rows are loaded,
  // which overwrites selectedUserIds with a partial set.
  const handleSelectionChange = useCallback(
    (ids: string[]) => {
      if (!initialized) return;
      const kept = new Set(ids);
      // Both rules run: one deselection can strip your own row and a last-group
      // member at once, and returning after the first leaves the other removed.
      const forcedIds: string[] = [];

      // Add mode can deselect your own row, which the member list disables — it would
      // drop the membership carrying your manager role. The backend rejects it too.
      if (
        currentUserId &&
        isOwnManagerRow(currentUserId) &&
        !kept.has(currentUserId)
      ) {
        toast.error("You can't remove yourself while managing this group");
        forcedIds.push(currentUserId);
      }

      // Same rule as the remove button; add mode can't disable a checkbox, so re-select.
      // Rows already forced above are skipped, so one row never raises two toasts.
      const strandedIds = allRows
        .filter((row) => {
          const rowId = row.id ?? row.email;
          return (
            !kept.has(rowId) &&
            !forcedIds.includes(rowId) &&
            isLastGroupMember(row)
          );
        })
        .map((row) => row.id ?? row.email);
      if (strandedIds.length > 0) {
        toast.error(
          "Some of those members would be left without a group. Add them to another group first."
        );
        forcedIds.push(...strandedIds);
      }

      setSelectedUserIds([...forcedIds, ...ids, ...hiddenMemberIds]);
    },
    [
      initialized,
      hiddenMemberIds,
      currentUserId,
      isOwnManagerRow,
      isLastGroupMember,
      allRows,
    ]
  );

  async function handleSave() {
    if (isSubmittingRef.current) return;

    const trimmed = groupName.trim();
    if (!trimmed) {
      toast.error("Group name is required");
      return;
    }

    // Re-fetch group to check sync status before saving
    const freshGroups = await fetch(SWR_KEYS.adminUserGroupsWithDefault).then(
      (r) => r.json()
    );
    const freshGroup = freshGroups.find((g: UserGroup) => g.id === groupId);
    if (freshGroup && !freshGroup.is_up_to_date) {
      toast.error(
        "This group is currently syncing. Please wait a moment and try again."
      );
      return;
    }

    isSubmittingRef.current = true;
    setIsSubmitting(true);
    try {
      // Rename if name changed
      if (canManage && group && trimmed !== group.name) {
        await renameGroup(group.id, trimmed);
      }

      // Update members and cc_pairs
      await updateGroup(groupId, selectedUserIds, selectedCcPairIds);

      if (canManage) {
        // Update agent sharing (add/remove this group from changed agents)
        await updateAgentGroupSharing(
          groupId,
          initialAgentIdsRef.current,
          selectedAgentIds
        );

        // Update document set sharing (add/remove this group from changed doc sets)
        await updateDocSetGroupSharing(
          groupId,
          initialDocSetIdsRef.current,
          selectedDocSetIds
        );
      }

      // Group-scoped create/update/delete routes admit a group admin, so their full save
      // (including PUT/DELETE of existing limits) is authorized.
      if (isEnterpriseTier && canEditTokenLimits) {
        await saveTokenLimits(groupId, tokenLimits, tokenRateLimits ?? []);
      }

      // Bulk desired-state replace; FULL_ADMIN only.
      if (canEditPermissions) {
        await saveGroupPermissions(groupId, enabledPermissions);
      }

      // Last: granting incognito access must not outlive a save that then
      // fails, which would report an error while members already had it.
      if (canManage && group && incognitoEnabled !== group.incognito_enabled) {
        await setGroupIncognito(groupId, incognitoEnabled);
      }

      // Update refs so subsequent saves diff correctly
      initialAgentIdsRef.current = selectedAgentIds;
      initialDocSetIdsRef.current = selectedDocSetIds;

      refreshGroupLists(mutate);
      mutate(SWR_KEYS.userGroupTokenRateLimit(groupId));
      if (canEditPermissions) {
        mutate(SWR_KEYS.userGroupPermissions(groupId));
      }
      // Membership and the incognito flag both feed chat availability.
      mutate(SWR_KEYS.incognitoAvailability);
      toast.success(`Group "${trimmed}" updated`);
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to update group");
    } finally {
      isSubmittingRef.current = false;
      setIsSubmitting(false);
    }
  }

  async function handleDelete() {
    setIsDeleting(true);
    try {
      await deleteGroup(groupId);
      refreshGroupLists(mutate);
      toast.success(`Group "${group?.name}" deleted`);
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete group");
    } finally {
      setIsDeleting(false);
      setShowDeleteModal(false);
    }
  }

  // 404 state: a group the caller can't act on reads as absent, so a deep link to a
  // default group as a non-full-admin lands here — matching the list, which hides it.
  if (!isLoading && !error && !canManageMembers) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgUsers}
          title="Group Not Found"
          divider
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title="Group not found"
            description="This group doesn't exist or may have been deleted."
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const headerActions = (
    <Section flexDirection="row" gap={2} width="auto" height="auto">
      <Button
        prominence="secondary"
        onClick={() => router.push("/admin/groups")}
      >
        Cancel
      </Button>
      <Button
        onClick={handleSave}
        disabled={
          !groupName.trim() || isSubmitting || isSyncing || !canManageMembers
        }
        tooltip={
          isSyncing
            ? "Document embeddings are being updated due to recent changes to this group."
            : undefined
        }
      >
        {isSubmitting ? "Saving..." : isSyncing ? "Syncing..." : "Save Changes"}
      </Button>
    </Section>
  );

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgUsers}
          title="Edit Group"
          divider
          rightChildren={headerActions}
        />

        <SettingsLayouts.Body>
          {isLoading && <SvgSimpleLoader />}

          {error && (
            <Text as="p" secondaryBody text03>
              Failed to load group data.
            </Text>
          )}

          {!isLoading && !error && group && (
            <>
              {isDefaultGroup && (
                <MessageCard
                  variant="info"
                  title="System group"
                  description="Onyx manages this group. Members are the only thing it holds, and the only thing you can change."
                />
              )}

              {/* Group Name */}
              <Section
                gap={2}
                height="auto"
                alignItems="stretch"
                justifyContent="start"
              >
                <Text mainUiBody text04>
                  Group Name
                </Text>
                <InputTypeIn
                  placeholder="Name your group"
                  value={groupName}
                  variant={canManage ? "primary" : "readOnly"}
                  onChange={(e) => setGroupName(e.target.value)}
                />
              </Section>

              <Divider paddingParallel={0} paddingPerpendicular={0} />

              {/* Members table */}
              <Section
                gap={3}
                height="auto"
                alignItems="stretch"
                justifyContent="start"
              >
                <Section
                  flexDirection="row"
                  gap={2}
                  height="auto"
                  alignItems="center"
                  justifyContent="start"
                >
                  <InputTypeIn
                    value={searchTerm}
                    onChange={(e) => setSearchTerm(e.target.value)}
                    placeholder={
                      isAddingMembers
                        ? "Search users and accounts..."
                        : "Search members..."
                    }
                    searchIcon
                  />
                  {isAddingMembers ? (
                    <Button
                      prominence="secondary"
                      onClick={() => setIsAddingMembers(false)}
                    >
                      Done
                    </Button>
                  ) : (
                    canManageMembers && (
                      <Button
                        prominence="tertiary"
                        icon={SvgPlusCircle}
                        onClick={() => setIsAddingMembers(true)}
                      >
                        Add
                      </Button>
                    )
                  )}
                </Section>

                {isAddingMembers ? (
                  <Table
                    key="add-members"
                    data={allRows as MemberRow[]}
                    columns={addModeColumns}
                    getRowId={(row) => row.id ?? row.email}
                    pageSize={PAGE_SIZE}
                    searchTerm={searchTerm}
                    selectionBehavior="multi-select"
                    initialRowSelection={currentRowSelection}
                    onSelectionChange={handleSelectionChange}
                    footer={{}}
                    emptyState={
                      <IllustrationContent
                        illustration={SvgNoResult}
                        title="No users found"
                        description="No users match your search."
                      />
                    }
                  />
                ) : (
                  <Table
                    data={memberRows}
                    columns={memberColumns}
                    getRowId={(row) => row.id ?? row.email}
                    pageSize={PAGE_SIZE}
                    searchTerm={searchTerm}
                    footer={{}}
                    emptyState={
                      <IllustrationContent
                        illustration={SvgNoResult}
                        title="No members"
                        description="Add members to this group."
                      />
                    }
                  />
                )}
              </Section>

              {canEditPermissions && (
                <GroupPermissionsSection
                  enabledPermissions={enabledPermissions}
                  onPermissionsChange={setEnabledPermissions}
                />
              )}

              {/* a default group has no sharing, limits or incognito to show */}
              {canManage && (
                <>
                  <SharedGroupResources
                    selectedCcPairIds={selectedCcPairIds}
                    onCcPairIdsChange={setSelectedCcPairIds}
                    selectedDocSetIds={selectedDocSetIds}
                    onDocSetIdsChange={setSelectedDocSetIds}
                    selectedAgentIds={selectedAgentIds}
                    onAgentIdsChange={setSelectedAgentIds}
                    attachedAgents={group?.personas}
                  />

                  <TokenLimitSection
                    limits={tokenLimits}
                    onLimitsChange={setTokenLimits}
                    disabled={!isEnterpriseTier || !canEditTokenLimits}
                    disabledTooltip={tokenLimitsDisabledTooltip}
                  />
                </>
              )}

              {canManage && showIncognitoField && (
                <Card border="solid" rounding={4}>
                  <Section alignItems="start" height="fit">
                    <InputHorizontal
                      title="Incognito Chats"
                      description="Members of this group may start incognito chats."
                      withLabel
                    >
                      <Switch
                        checked={incognitoEnabled}
                        onCheckedChange={setIncognitoEnabled}
                      />
                    </InputHorizontal>
                  </Section>
                </Card>
              )}

              {/* Delete This Group */}
              {canDelete && (
                <Card border="solid" rounding={4}>
                  <Section alignItems="start" height="fit">
                    <InputHorizontal
                      title="Delete This Group"
                      description="Members will lose access to any resources shared with this group."
                      center
                    >
                      <Button
                        variant="danger"
                        prominence="secondary"
                        icon={SvgTrash}
                        onClick={() => setShowDeleteModal(true)}
                      >
                        Delete Group
                      </Button>
                    </InputHorizontal>
                  </Section>
                </Card>
              )}
            </>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      {showDeleteModal && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Group"
          onClose={() => setShowDeleteModal(false)}
          submit={
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? "Deleting..." : "Delete"}
            </Button>
          }
        >
          <Text as="p" text03>
            Members of group{" "}
            <Text as="span" text05>
              {group?.name}
            </Text>{" "}
            will lose access to any resources shared with this group, unless
            they have been granted access directly. Deletion cannot be undone.
          </Text>
        </ConfirmationModalLayout>
      )}
    </>
  );
}

export default EditGroupPage;
