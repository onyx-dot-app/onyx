"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Divider } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgUsers, SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { InputTypeIn } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import { toast } from "@/hooks/useToast";
import useGroupMemberCandidates from "./useGroupMemberCandidates";
import {
  createGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
} from "./svc";
import { memberTableColumns, PAGE_SIZE } from "./shared";
import SharedGroupResources from "@/refresh-pages/admin/GroupsPage/SharedGroupResources";
import TokenLimitSection from "./TokenLimitSection";
import type { TokenLimit } from "./TokenLimitSection";

function CreateGroupPage() {
  const router = useRouter();
  const [groupName, setGroupName] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selectedCcPairIds, setSelectedCcPairIds] = useState<number[]>([]);
  const [selectedDocSetIds, setSelectedDocSetIds] = useState<number[]>([]);
  const [selectedAgentIds, setSelectedAgentIds] = useState<number[]>([]);
  const [tokenLimits, setTokenLimits] = useState<TokenLimit[]>([
    { tokenBudget: null, periodHours: null },
  ]);

  const { rows: allRows, isLoading, error } = useGroupMemberCandidates();

  async function handleCreate() {
    const trimmed = groupName.trim();
    if (!trimmed) {
      toast.error("请输入用户组名称");
      return;
    }

    setIsSubmitting(true);
    try {
      const groupId = await createGroup(
        trimmed,
        selectedUserIds,
        selectedCcPairIds
      );
      await updateAgentGroupSharing(groupId, [], selectedAgentIds);
      await updateDocSetGroupSharing(groupId, [], selectedDocSetIds);
      await saveTokenLimits(groupId, tokenLimits, []);
      toast.success(`用户组“${trimmed}”已创建`);
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "创建用户组失败");
    } finally {
      setIsSubmitting(false);
    }
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
        onClick={handleCreate}
        disabled={!groupName.trim() || isSubmitting}
      >
        创建
      </Button>
    </Section>
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUsers}
        title="创建用户组"
        divider
        rightChildren={headerActions}
      />

      <SettingsLayouts.Body>
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
        {isLoading && <SvgSimpleLoader />}

        {error ? (
          <Text as="p" secondaryBody text03>
            加载用户失败。
          </Text>
        ) : null}

        {!isLoading && !error && (
          <Section
            gap={0.75}
            height="auto"
            alignItems="stretch"
            justifyContent="start"
          >
            <InputTypeIn
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="搜索用户和账号..."
              searchIcon
            />
            <Table
              data={allRows}
              columns={memberTableColumns}
              getRowId={(row) => row.id ?? row.email}
              pageSize={PAGE_SIZE}
              searchTerm={searchTerm}
              selectionBehavior="multi-select"
              onSelectionChange={setSelectedUserIds}
              footer={{}}
              emptyState={
                <IllustrationContent
                  illustration={SvgNoResult}
                  title="未找到用户"
                  description="没有用户匹配你的搜索。"
                />
              }
            />
          </Section>
        )}
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
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default CreateGroupPage;
