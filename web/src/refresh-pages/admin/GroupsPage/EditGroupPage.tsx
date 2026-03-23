"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import { Table, Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgUsers, SvgTrash } from "@opal/icons";
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
import type { ApiKeyDescriptor, TokenRateLimitDisplay } from "./interfaces";
import { apiKeyToMemberRow, memberTableColumns, PAGE_SIZE } from "./shared";
import {
  USER_GROUP_URL,
  renameGroup,
  updateGroup,
  deleteGroup,
  updateAgentGroupSharing,
  saveTokenLimits,
} from "./svc";
import SharedGroupResources from "@/refresh-pages/admin/GroupsPage/SharedGroupResources";
import TokenLimitSection from "./TokenLimitSection";
import type { TokenLimit } from "./TokenLimitSection";

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
  const initialAgentIdsRef = useRef<number[]>([]);

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
      setSelectedDocSetIds(group.document_sets.map((ds) => ds.id));
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

  const initialRowSelection = useMemo(() => {
    if (!group) return {};
    const sel: Record<string, boolean> = {};
    for (const u of group.users) {
      sel[u.id] = true;
    }
    return sel;
  }, [group]);

  // Guard onSelectionChange: ignore updates until the form is fully initialized.
  // Without this, TanStack fires onSelectionChange before all rows are loaded,
  // which overwrites selectedUserIds with a partial set.
  const handleSelectionChange = useCallback(
    (ids: string[]) => {
      if (!initialized) return;
      setSelectedUserIds(ids);
    },
    [initialized]
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

      // Save token rate limits (create/update/delete)
      await saveTokenLimits(groupId, tokenLimits, tokenRateLimits ?? []);

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
        variant="danger"
        prominence="tertiary"
        icon={SvgTrash}
        onClick={() => setShowDeleteModal(true)}
        tooltip="Delete group"
      />
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
        {isSubmitting ? "Saving..." : isSyncing ? "Syncing..." : "Save"}
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
                <InputTypeIn
                  value={searchTerm}
                  onChange={(e) => setSearchTerm(e.target.value)}
                  placeholder="Search users and accounts..."
                  leftSearchIcon
                />
                <Table
                  data={allRows}
                  columns={memberTableColumns}
                  getRowId={(row) => row.id ?? row.email}
                  qualifier="avatar"
                  pageSize={PAGE_SIZE}
                  searchTerm={searchTerm}
                  selectionBehavior="multi-select"
                  initialRowSelection={initialRowSelection}
                  initialViewSelected
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
            </>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      {showDeleteModal && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="Delete Group"
          description={`Are you sure you want to delete "${group?.name}"? This action cannot be undone.`}
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
        />
      )}
    </>
  );
}

export default EditGroupPage;
