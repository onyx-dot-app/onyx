"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Table, Button } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgUsers } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import Separator from "@/refresh-components/Separator";
import { toast } from "@/hooks/useToast";
import useGroupMemberCandidates from "./useGroupMemberCandidates";
import {
  createGroup,
  updateAgentGroupSharing,
  updateDocSetGroupSharing,
  saveTokenLimits,
} from "./svc";
import { useMemberTableColumns, PAGE_SIZE } from "./shared";
import SharedGroupResources from "@/refresh-pages/admin/GroupsPage/SharedGroupResources";
import TokenLimitSection from "./TokenLimitSection";
import type { TokenLimit } from "./TokenLimitSection";

function CreateGroupPage() {
  const router = useRouter();
  const t = useTranslations("admin.groups");
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

  const memberTableColumns = useMemberTableColumns();

  const { rows: allRows, isLoading, error } = useGroupMemberCandidates();

  async function handleCreate() {
    const trimmed = groupName.trim();
    if (!trimmed) {
      toast.error(t("groupNameRequired"));
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
      toast.success(t("groupCreated", { name: trimmed }));
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : t("failedToCreateGroup"));
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
        {t("cancel")}
      </Button>
      <Button
        onClick={handleCreate}
        disabled={!groupName.trim() || isSubmitting}
      >
        {t("create")}
      </Button>
    </Section>
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUsers}
        title={t("createGroup")}
        separator
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
            {t("groupName")}
          </Text>
          <InputTypeIn
            placeholder={t("nameYourGroup")}
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
          />
        </Section>

        <Separator noPadding />

        {/* Members table */}
        {isLoading && <SimpleLoader />}

        {error ? (
          <Text as="p" secondaryBody text03>
            {t("failedToLoadUsers")}
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
              placeholder={t("searchUsersAndAccounts")}
              leftSearchIcon
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
                  title={t("noUsersFound")}
                  description={t("noUsersMatchSearch")}
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
