"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import useSWR from "swr";
import { Table, createTableColumns, Button } from "@opal/components";
import { Content, IllustrationContent } from "@opal/layouts";
import {
  SvgUser,
  SvgUserManage,
  SvgUsers,
  SvgGlobe,
  SvgSlack,
} from "@opal/icons";
import SvgNoResult from "@opal/illustrations/no-result";
import type { IconFunctionComponent } from "@opal/types";
import * as SettingsLayouts from "@/layouts/settings-layouts";
import InputTypeIn from "@/refresh-components/inputs/InputTypeIn";
import Text from "@/refresh-components/texts/Text";
import SimpleLoader from "@/refresh-components/loaders/SimpleLoader";
import { toast } from "@/hooks/useToast";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useAdminUsers from "@/hooks/useAdminUsers";
import { UserRole, UserStatus, USER_ROLE_LABELS } from "@/lib/types";
import type { UserRow } from "@/refresh-pages/admin/UsersPage/interfaces";
import { getInitials } from "@/refresh-pages/admin/UsersPage/utils";
import { createGroup } from "./svc";
import Separator from "@/refresh-components/Separator";

// ---------------------------------------------------------------------------
// API key (service account) types
// ---------------------------------------------------------------------------

interface ApiKeyDescriptor {
  api_key_id: number;
  api_key_display: string;
  api_key_name: string | null;
  api_key_role: UserRole;
  user_id: string;
}

/** Extends UserRow with an optional API key display for service accounts. */
interface MemberRow extends UserRow {
  api_key_display?: string;
}

function apiKeyToMemberRow(key: ApiKeyDescriptor): MemberRow {
  return {
    id: key.user_id,
    email: "Service Account",
    role: key.api_key_role,
    status: UserStatus.ACTIVE,
    is_active: true,
    is_scim_synced: false,
    personal_name: key.api_key_name ?? "Unnamed Key",
    created_at: null,
    updated_at: null,
    groups: [],
    api_key_display: key.api_key_display,
  };
}

// ---------------------------------------------------------------------------
// Role icon mapping (mirrors UsersPage/UserRoleCell)
// ---------------------------------------------------------------------------

const ROLE_ICONS: Partial<Record<UserRole, IconFunctionComponent>> = {
  [UserRole.ADMIN]: SvgUserManage,
  [UserRole.GLOBAL_CURATOR]: SvgGlobe,
  [UserRole.SLACK_USER]: SvgSlack,
};

// ---------------------------------------------------------------------------
// Column renderers
// ---------------------------------------------------------------------------

function renderNameColumn(email: string, row: MemberRow) {
  return (
    <Content
      sizePreset="main-ui"
      variant="section"
      title={row.personal_name ?? email}
      description={row.personal_name ? email : undefined}
    />
  );
}

function renderAccountTypeColumn(_value: unknown, row: MemberRow) {
  const Icon = (row.role && ROLE_ICONS[row.role]) || SvgUser;
  return (
    <div className="flex flex-row items-center gap-1">
      <Icon className="w-4 h-4 text-text-03" />
      <Text as="span" mainUiBody text03>
        {row.role ? USER_ROLE_LABELS[row.role] ?? row.role : "\u2014"}
      </Text>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Columns
// ---------------------------------------------------------------------------

const tc = createTableColumns<MemberRow>();

const columns = [
  tc.qualifier({
    content: "avatar-user",
    getInitials: (row) => getInitials(row.personal_name, row.email),
    selectable: true,
  }),
  tc.column("email", {
    header: "Name",
    weight: 25,
    minWidth: 180,
    cell: renderNameColumn,
  }),
  tc.column("api_key_display", {
    header: "",
    weight: 15,
    minWidth: 100,
    enableSorting: false,
    cell: (value) =>
      value ? (
        <Text as="span" secondaryBody text03>
          {value}
        </Text>
      ) : null,
  }),
  tc.column("role", {
    header: "Account Type",
    weight: 15,
    minWidth: 140,
    cell: renderAccountTypeColumn,
  }),
  tc.actions({
    showSorting: false,
  }),
];

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

const PAGE_SIZE = 10;

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
    <div className="flex flex-row items-center gap-2 shrink-0">
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
    </div>
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
        <div className="flex flex-col gap-2">
          <Text mainUiBody text04>
            Group Name
          </Text>
          <InputTypeIn
            placeholder="Name your group"
            value={groupName}
            onChange={(e) => setGroupName(e.target.value)}
          />
        </div>

        <Separator noPadding />

        {/* Members table */}
        {isLoading && <SimpleLoader />}

        {error && (
          <Text as="p" secondaryBody text03>
            Failed to load users.
          </Text>
        )}

        {!isLoading && !error && (
          <div className="flex flex-col gap-3">
            <InputTypeIn
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Search users and accounts..."
              leftSearchIcon
            />
            <Table
              data={allRows}
              columns={columns}
              getRowId={(row) => row.id ?? row.email}
              qualifier="avatar"
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
          </div>
        )}
      </SettingsLayouts.Body>
    </SettingsLayouts.Root>
  );
}

export default CreateGroupPage;
