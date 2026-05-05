"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Table, Button, Divider } from "@opal/components";
import { IllustrationContent } from "@opal/layouts";
import { SvgUsers } from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import { Section } from "@/layouts/general-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
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
      toast.error("Group name is required");
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
      toast.success(`Group "${trimmed}" created`);
      router.push("/admin/groups");
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Failed to create group");
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
        Cancel
      </Button>
      <Button
        onClick={handleCreate}
        disabled={!groupName.trim() || isSubmitting}
      >
        Create
      </Button>
    </Section>
  );

  return (
    <SettingsLayouts.Root>
      <SettingsLayouts.Header
        icon={SvgUsers}
        title="Create Group"
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
            Group Name
          </Text>
          <InputTypeIn
            placeholder="Name your group"
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
          />
        </Section>

        <Divider paddingParallel="fit" paddingPerpendicular="fit" />

        {/* Members table */}
        {isLoading && <SimpleLoader />}

        {error ? (
          <Text as="p" secondaryBody text03>
            Failed to load users.
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
              placeholder="Search users and accounts..."
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
                  title="No users found"
                  description="No users match your search."
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
