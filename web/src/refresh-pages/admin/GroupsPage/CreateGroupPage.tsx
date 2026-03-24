"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
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
import { errorHandlingFetcher } from "@/lib/fetcher";
import useAdminUsers from "@/hooks/useAdminUsers";
import type { ApiKeyDescriptor, MemberRow } from "./interfaces";
import { createGroup } from "./svc";
import { apiKeyToMemberRow, memberTableColumns, PAGE_SIZE } from "./shared";

function CreateGroupPage() {
  const router = useRouter();
  const [groupName, setGroupName] = useState("");
  const [selectedUserIds, setSelectedUserIds] = useState<string[]>([]);
  const [searchTerm, setSearchTerm] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const { users, isLoading: usersLoading, error: usersError } = useAdminUsers();

  const {
    data: apiKeys,
    isLoading: apiKeysLoading,
    error: apiKeysError,
  } = useSWR<ApiKeyDescriptor[]>("/api/admin/api-key", errorHandlingFetcher);

  const isLoading = usersLoading || apiKeysLoading;
  const error = usersError ?? apiKeysError;

  const allRows: MemberRow[] = useMemo(() => {
    const activeUsers = users.filter((u) => u.is_active);
    const serviceAccountRows = (apiKeys ?? []).map(apiKeyToMemberRow);
    return [...activeUsers, ...serviceAccountRows];
  }, [users, apiKeys]);

  async function handleCreate() {
    const trimmed = groupName.trim();
    if (!trimmed) {
      toast.error("Group name is required");
      return;
    }

    setIsSubmitting(true);
    try {
      await createGroup(trimmed, selectedUserIds);
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
        prominence="tertiary"
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
    <SettingsLayouts.Root width="lg">
      <SettingsLayouts.Header
        icon={SvgUsers}
        title="Create Group"
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
        {isLoading && <SimpleLoader />}

        {error && (
          <Text as="p" secondaryBody text03>
            Failed to load users.
          </Text>
        )}

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
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default CreateGroupPage;
