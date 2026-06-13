"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR, { useSWRConfig } from "swr";
import useGroupMemberCandidates from "./useGroupMemberCandidates";
import { Table, Button, Divider } from "@opal/components";
import { IllustrationContent, InputHorizontal } from "@opal/layouts";
import {
  SvgUsers,
  SvgTrash,
  SvgMinusCircle,
  SvgPlusCircle,
  SvgSimpleLoader,
} from "@opal/icons";
import { markdown } from "@opal/utils";
import IconButton from "@/refresh-components/buttons/IconButton";
import Card from "@/refresh-components/cards/Card";
import SvgNoResult from "@opal/illustrations/no-result";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { InputTypeIn } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import ConfirmationModalLayout from "@/refresh-components/layouts/ConfirmationModalLayout";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher, skipRetryOnAuthError } from "@/lib/fetcher";
import type { UserGroup } from "@/lib/types";
import { useSettingsContext } from "@/providers/SettingsProvider";
import { Tier } from "@/interfaces/settings";
import { tierAtLeast } from "@/lib/tiers";
import type { MemberRow, TokenRateLimitDisplay } from "./interfaces";
import { baseColumns, memberTableColumns, tc, PAGE_SIZE } from "./shared";
import {
  renameGroup,
  updateGroup,
  deleteGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
} from "./svc";
import { SWR_KEYS } from "@/lib/swr-keys";
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
  const settings = useSettingsContext();
  const isEnterpriseTier = tierAtLeast(
    settings?.settings.tier,
    Tier.ENTERPRISE
  );
  const tokenLimitsDisabledTooltip = markdown(
    "Token 速率限制仅在 [Glomi AI 企业版](/admin/billing) 中可用。"
  );

  // Fetch the group data — poll every 5s while syncing so the UI updates
  // automatically when the backend finishes processing the previous edit.
  const {
    data: groups,
    isLoading: groupLoading,
    error: groupError,
  } = useSWR<UserGroup[]>(SWR_KEYS.adminUserGroups, errorHandlingFetcher, {
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

  // Fetch token rate limits for this group. Skip retry on tier-gated 402
  // (BUSINESS-tier tenants don't have access) so SWR doesn't churn the form
  // by repeatedly flipping its isLoading state.
  const { data: tokenRateLimits, isLoading: tokenLimitsLoading } = useSWR<
    TokenRateLimitDisplay[]
  >(SWR_KEYS.userGroupTokenRateLimit(groupId), errorHandlingFetcher, {
    onErrorRetry: skipRetryOnAuthError,
  });

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

  // Users + service accounts (curator-accessible — see hook docs).
  const {
    rows: allRows,
    isLoading: candidatesLoading,
    error: candidatesError,
  } = useGroupMemberCandidates();

  const isLoading = groupLoading || candidatesLoading || tokenLimitsLoading;
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
      toast.error("请输入用户组名称");
      return;
    }

    // Re-fetch group to check sync status before saving
    const freshGroups = await fetch(SWR_KEYS.adminUserGroups).then((r) =>
      r.json()
    );
    const freshGroup = freshGroups.find((g: UserGroup) => g.id === groupId);
    if (freshGroup && !freshGroup.is_up_to_date) {
      toast.error(
        "此用户组正在同步中。请稍等片刻后重试。"
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

      // Save token rate limits (create/update/delete) — Enterprise-only
      if (isEnterpriseTier) {
        await saveTokenLimits(groupId, tokenLimits, tokenRateLimits ?? []);
      }

      // Update refs so subsequent saves diff correctly
      initialAgentIdsRef.current = selectedAgentIds;
      initialDocSetIdsRef.current = selectedDocSetIds;

      mutate(SWR_KEYS.adminUserGroups);
      mutate(SWR_KEYS.userGroupTokenRateLimit(groupId));
      toast.success(`用户组“${trimmed}”已更新`);
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "更新用户组失败");
    } finally {
      isSubmittingRef.current = false;
      setIsSubmitting(false);
    }
  }

  async function handleDelete() {
    setIsDeleting(true);
    try {
      await deleteGroup(groupId);
      mutate(SWR_KEYS.adminUserGroups);
      toast.success(`用户组“${group?.name}”已删除`);
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "删除用户组失败");
    } finally {
      setIsDeleting(false);
      setShowDeleteModal(false);
    }
  }

  // 404 state
  if (!isLoading && !error && !group) {
    return (
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgUsers}
          title="未找到用户组"
          divider
        />
        <SettingsLayouts.Body>
          <IllustrationContent
            illustration={SvgNoResult}
            title="未找到用户组"
            description="此用户组不存在，或可能已被删除。"
          />
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>
    );
  }

  const headerActions = (
    <Section flexDirection="row" gap={0.5} width="auto" height="auto">
      <Button
        prominence="secondary"
        onClick={() => router.push("/admin/groups")}
      >
        取消
      </Button>
      <Button
        onClick={handleSave}
        disabled={!groupName.trim() || isSubmitting || isSyncing}
        tooltip={
          isSyncing
            ? "由于此用户组最近发生变更，文档向量正在更新。"
            : undefined
        }
      >
        {isSubmitting ? "正在保存..." : isSyncing ? "同步中..." : "保存更改"}
      </Button>
    </Section>
  );

  return (
    <>
      <SettingsLayouts.Root>
        <SettingsLayouts.Header
          icon={SvgUsers}
          title="编辑用户组"
          divider
          rightChildren={headerActions}
        />

        <SettingsLayouts.Body>
          {isLoading && <SvgSimpleLoader />}

          {error && (
            <Text as="p" secondaryBody text03>
              加载用户组数据失败。
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
                  用户组名称
                </Text>
                <InputTypeIn
                  placeholder="为用户组命名"
                  value={groupName}
                  onChange={(e) => setGroupName(e.target.value)}
                />
              </Section>

              <Divider paddingParallel="fit" paddingPerpendicular="fit" />

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
                        ? "搜索用户和账号..."
                        : "搜索成员..."
                    }
                    searchIcon
                  />
                  {isAddingMembers ? (
                    <Button
                      prominence="secondary"
                      onClick={() => setIsAddingMembers(false)}
                    >
                      完成
                    </Button>
                  ) : (
                    <Button
                      prominence="tertiary"
                      icon={SvgPlusCircle}
                      onClick={() => setIsAddingMembers(true)}
                    >
                      添加
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
                        title="未找到用户"
                        description="没有用户与你的搜索匹配。"
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
                        title="暂无成员"
                        description="向此用户组添加成员。"
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
                disabled={!isEnterpriseTier}
                disabledTooltip={tokenLimitsDisabledTooltip}
              />

              {/* Delete This Group */}
              <Card>
                <InputHorizontal
                  title="删除此用户组"
                  description="成员将失去对此用户组共享资源的访问权限。"
                  center
                >
                  <Button
                    variant="danger"
                    prominence="secondary"
                    icon={SvgTrash}
                    onClick={() => setShowDeleteModal(true)}
                  >
                    删除用户组
                  </Button>
                </InputHorizontal>
              </Card>
            </>
          )}
        </SettingsLayouts.Body>
      </SettingsLayouts.Root>

      {showDeleteModal && (
        <ConfirmationModalLayout
          icon={SvgTrash}
          title="删除用户组"
          onClose={() => setShowDeleteModal(false)}
          submit={
            <Button
              variant="danger"
              onClick={handleDelete}
              disabled={isDeleting}
            >
              {isDeleting ? "正在删除..." : "删除"}
            </Button>
          }
        >
          <Text as="p" text03>
            用户组{" "}
            <Text as="span" text05>
              {group?.name}
            </Text>{" "}
            的成员将失去对此用户组共享资源的访问权限，除非他们已被直接授予访问权限。删除后无法撤销。
          </Text>
        </ConfirmationModalLayout>
      )}
    </>
  );
}

export default EditGroupPage;
