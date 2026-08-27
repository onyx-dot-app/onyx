"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Table, Button, Divider } from "@opal/components";
import { IllustrationContent, toast } from "@opal/layouts";
import { SvgUsers, SvgSimpleLoader } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import { SettingsLayouts } from "@opal/layouts";
import { Section } from "@/layouts/general-layouts";
import { InputTypeIn } from "@opal/components";
import Text from "@/refresh-components/texts/Text";
import useGroupMemberCandidates from "./useGroupMemberCandidates";
import {
  createGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
  saveGroupPermissions,
} from "./svc";
import { makeMemberTableColumns, PAGE_SIZE } from "./shared";
import SharedGroupResources from "@/views/admin/GroupsPage/SharedGroupResources";
import GroupPermissionsSection from "./GroupPermissionsSection";
import TokenLimitSection from "./TokenLimitSection";
import type { TokenLimit } from "./TokenLimitSection";
import { useUser } from "@/providers/UserProvider";

function CreateGroupPage() {
  const t = useTranslations("admin.groups");
  const router = useRouter();
  const [groupName, setGroupName] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [selectedCcPairIds, setSelectedCcPairIds] = useState<number[]>([]);
  const [selectedDocSetIds, setSelectedDocSetIds] = useState<number[]>([]);
  const [selectedAgentIds, setSelectedAgentIds] = useState<number[]>([]);
  const [enabledPermissions, setEnabledPermissions] = useState<Set<string>>(
    new Set()
  );
  const [tokenLimits, setTokenLimits] = useState<TokenLimit[]>([
    {
      tokenId: null,
      enabled: true,
      tokenBudget: null,
      periodDays: null,
      costBudgetDollars: null,
    },
  ]);

  const { isAdmin } = useUser();
  const { rows: allRows, isLoading, error } = useGroupMemberCandidates();

  const memberColumns = useMemo(
    () =>
      makeMemberTableColumns({
        name: t("members.table.name.header"),
        accountType: t("members.table.accountType.header"),
        manager: t("members.managerTag.label"),
      }),
    [t]
  );

  async function handleCreate() {
    const trimmed = groupName.trim();
    if (!trimmed) {
      toast.error(t("form.toasts.nameRequired"));
      return;
    }

    setIsSubmitting(true);
    try {
      const groupId = await createGroup(
        trimmed,
        selectedUserIds,
        selectedCcPairIds
      );
      if (isAdmin) {
        await saveGroupPermissions(groupId, enabledPermissions);
      }
      await updateAgentGroupSharing(groupId, [], selectedAgentIds);
      await updateDocSetGroupSharing(groupId, [], selectedDocSetIds);
      await saveTokenLimits(groupId, tokenLimits, []);
      toast.success(t("create.toasts.created", { name: trimmed }));
      router.push("/admin/groups");
    } catch (e) {
      toast.error(
        e instanceof Error ? e.message : t("create.toasts.createFailed")
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  const headerActions = (
    <Section flexDirection="row" gap={2} width="auto" height="auto">
      <Button
        prominence="secondary"
        onClick={() => router.push("/admin/groups")}
      >
        {t("form.cancel.label")}
      </Button>
      <Button
        onClick={handleCreate}
        disabled={!groupName.trim() || isSubmitting}
      >
        {t("create.submit.label")}
      </Button>
    </Section>
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUsers}
        title={t("create.header.title")}
        divider
        rightChildren={headerActions}
      />

      <SettingsLayouts.Body>
        {/* Group Name */}
        <Section
          gap={2}
          height="auto"
          alignItems="stretch"
          justifyContent="start"
        >
          <Text mainUiBody text04>
            {t("form.name.label")}
          </Text>
          <InputTypeIn
            placeholder={t("form.name.placeholder")}
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
          />
        </Section>

        <Divider paddingParallel={0} paddingPerpendicular={0} />

        {/* Members table */}
        {isLoading && <SvgSimpleLoader />}

        {error ? (
          <Text as="p" secondaryBody text03>
            {t("members.loadError.text")}
          </Text>
        ) : null}

        {!isLoading && !error && (
          <Section
            gap={3}
            height="auto"
            alignItems="stretch"
            justifyContent="start"
          >
            <InputTypeIn
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder={t("members.searchUsers.placeholder")}
              searchIcon
            />
            <Table
              data={allRows}
              columns={memberColumns}
              getRowId={(row) => row.id ?? row.email}
              pageSize={PAGE_SIZE}
              searchTerm={searchTerm}
              selectionBehavior="multi-select"
              onSelectionChange={setSelectedUserIds}
              footer={{}}
              emptyState={
                <IllustrationContent
                  illustration={SvgNoResult}
                  title={t("members.noUsers.title")}
                  description={t("members.noUsers.description")}
                />
              }
            />
          </Section>
        )}
        {isAdmin && (
          <GroupPermissionsSection
            enabledPermissions={enabledPermissions}
            onPermissionsChange={setEnabledPermissions}
          />
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
