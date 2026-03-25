"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { Table, Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgUsers, SvgTrash, SvgMinusCircle, SvgPlusCircle } from "@opal/icons";
import IconButton from "@/refresh-components/buttons/IconButton";
import Card from "@/refresh-components/cards/Card";
import * as InputLayouts from "@/layouts/input-layouts";
import SvgNoResult from "@opal/illustrations/no-result";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import Separator from "@/refresh-components/Separator";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useAdminUsers from "@/hooks/useAdminUsers";
import type { UserGroup } from "@/lib/types";
import type {
  ApiKeyDescriptor,
  MemberRow,
  TokenRateLimitDisplay,
} from "./interfaces";
import {
  apiKeyToMemberRow,
  baseColumns,
  memberTableColumns,
  tc,
  PAGE_SIZE,
} from "./shared";
import {
  USER_GROUP_URL,
  renameGroup,
  updateGroup,
  deleteGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
} from "./svc";
import SharedGroupResources from "@/refresh-pages/admin/GroupsPage/SharedGroupResources";
import TokenLimitSection from "./TokenLimitSection";
import type { TokenLimit } from "./TokenLimitSection";

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

  // Fetch the group data — poll every 5s while syncing so the UI updates
  // automatically when the backend finishes processing the previous edit.
  const {
    data: groups,
    isLoading: groupLoading,
    error: groupError,
  } = useSWR<UserGroup[]>(USER_GROUP_URL, errorHandlingFetcher, {
    refreshInterval: (latestData) => {
      const g = latestData?.find((g) => g.id === groupId);
      return g && !g.is_up_to_date ? 5000 : 0;
    },
  });

  const group = useMemo(
    () => groups?.find((g) => g.id === groupId) ?? null,
    [groups, groupId]
  );

  const isSyncing = group != null && !group.is_up_to_date;

  // Fetch token rate limits for this group
  const { data: tokenRateLimits, isLoading: tokenLimitsLoading } = useSWR<
    TokenRateLimitDisplay[]
  >(`/api/admin/token-rate-limits/user-group/${groupId}`, errorHandlingFetcher);

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
    { tokenBudget: null, periodHours: null },
  ]);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [initialized, setInitialized] = useState(false);
  const [isAddingMembers, setIsAddingMembers] = useState(false);
  const initialAgentIdsRef = useRef<number[]>([]);
  const initialDocSetIdsRef = useRef<number[]>([]);

  // Users and API keys
  const { users, isLoading: usersLoading, error: usersError } = useAdminUsers();

  const {
    data: apiKeys,
    isLoading: apiKeysLoading,
    error: apiKeysError,
  } = useSWR<ApiKeyDescriptor[]>("/api/admin/api-key", errorHandlingFetcher);

  const isLoading =
    groupLoading || usersLoading || apiKeysLoading || tokenLimitsLoading;
  const error = groupError ?? usersError ?? apiKeysError;

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
      setInitialized(true);
    }
  }, [group, initialized]);

  // Pre-populate token limits when fetched
  useEffect(() => {
    if (tokenRateLimits && tokenRateLimits.length > 0) {
      setTokenLimits(
        tokenRateLimits.map((trl) => ({
          tokenBudget: trl.token_budget,
          periodHours: trl.period_hours,
        }))
      );
    }
  }, [tokenRateLimits]);

  const allRows = useMemo(() => {
    const activeUsers = users.filter((u) => u.is_active);
    const serviceAccountRows = (apiKeys ?? []).map(apiKeyToMemberRow);
    return [...activeUsers, ...serviceAccountRows];
  }, [users, apiKeys]);

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

  const memberColumns = useMemo(
    () => [
      ...baseColumns,
      tc.actions({
        showSorting: false,
        showColumnVisibility: false,
        cell: (row: MemberRow) => (
          <IconButton
            icon={SvgMinusCircle}
            tertiary
            onClick={(e) => {
              e.stopPropagation();
              handleRemoveMember(row.id ?? row.email);
            }}
          />
        ),
      }),
    ],
    [handleRemoveMember]
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
      setSelectedUserIds([...ids, ...hiddenMemberIds]);
    },
    [initialized, hiddenMemberIds]
  );

  async function handleSave() {
    if (isSubmittingRef.current) return;

    const trimmed = groupName.trim();
    if (!trimmed) {
      toast.error("Group name is required");
      return;
    }

    // Re-fetch group to check sync status before saving
    const freshGroups = await fetch(USER_GROUP_URL).then((r) => r.json());
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
      if (group && trimmed !== group.name) {
        await renameGroup(group.id, trimmed);
      }

      // Update members and cc_pairs
      await updateGroup(groupId, selectedUserIds, selectedCcPairIds);

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

      // Save token rate limits (create/update/delete)
      await saveTokenLimits(groupId, tokenLimits, tokenRateLimits ?? []);

      // Update refs so subsequent saves diff correctly
      initialAgentIdsRef.current = selectedAgentIds;
      initialDocSetIdsRef.current = selectedDocSetIds;

      mutate(USER_GROUP_URL);
      mutate(`/api/admin/token-rate-limits/user-group/${groupId}`);
      toast.success(`Group "${trimmed}" updated`);
      router.push("/admin/groups2");
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
      mutate(USER_GROUP_URL);
      toast.success(`Group "${group?.name}" deleted`);
      router.push("/admin/groups2");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to delete group");
    } finally {
      setIsDeleting(false);
      setShowDeleteModal(false);
    }
  }

  // 404 state
  if (!isLoading && !error && !group) {
    return (
      <SettingsLayouts.Root width="sm">
        <SettingsLayouts.Header
          icon={SvgUsers}
          title="Group Not Found"
          separator
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
    <Section flexDirection="row" gap={0.5} width="auto" height="auto">
      <Button
        prominence="tertiary"
        onClick={() => router.push("/admin/groups2")}
      >
        Cancel
      </Button>
      <Button
        onClick={handleSave}
        disabled={!groupName.trim() || isSubmitting || isSyncing}
      >
        {isSubmitting ? "Saving..." : isSyncing ? "Syncing..." : "Save Changes"}
      </Button>
    </Section>
  );

  return (
    <>
      <SettingsLayouts.Root width="sm">
        <SettingsLayouts.Header
          icon={SvgUsers}
          title="Edit Group"
          separator
          rightChildren={headerActions}
        />

        <SettingsLayouts.Body>
          {isLoading && <SimpleLoader />}

          {error && (
            <Text as="p" secondaryBody text03>
              Failed to load group data.
            </Text>
          )}

          {!isLoading && !error && group && (
            <>
              {/* Group Name */}
              <Section
                gap={0.5}
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
                  onChange={(e) => setGroupName(e.target.value)}
                />
              </Section>

              <Separator noPadding />

              {/* Members table */}
              <Section
                gap={0.75}
                height="auto"
                alignItems="stretch"
                justifyContent="start"
              >
                <Section
                  flexDirection="row"
                  gap={0.5}
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
                    leftSearchIcon
                    className="flex-1"
                  />
                  {isAddingMembers ? (
                    <Button
                      prominence="secondary"
                      onClick={() => setIsAddingMembers(false)}
                    >
                      Done
                    </Button>
                  ) : (
                    <Button
                      prominence="tertiary"
                      icon={SvgPlusCircle}
                      onClick={() => setIsAddingMembers(true)}
                    >
                      Add
                    </Button>
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

              <SharedGroupResources
                selectedCcPairIds={selectedCcPairIds}
                onCcPairIdsChange={setSelectedCcPairIds}
                selectedDocSetIds={selectedDocSetIds}
                onDocSetIdsChange={setSelectedDocSetIds}
                selectedAgentIds={selectedAgentIds}
                onAgentIdsChange={setSelectedAgentIds}
              />

              <TokenLimitSection
                limits={tokenLimits}
                onLimitsChange={setTokenLimits}
              />

              {/* Delete This Group */}
              <Card>
                <InputLayouts.Horizontal
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
                </InputLayouts.Horizontal>
              </Card>
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
