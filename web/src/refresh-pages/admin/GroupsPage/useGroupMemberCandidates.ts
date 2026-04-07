"use client";

import { useMemo } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import { useUser } from "@/providers/UserProvider";
import { AccountType, UserStatus, type UserRole } from "@/lib/types";
import type {
  UserGroupInfo,
  UserRow,
} from "@/refresh-pages/admin/UsersPage/interfaces";
import type { ApiKeyDescriptor, MemberRow } from "./interfaces";

// Backend response shape for `/api/manage/users?include_api_keys=true`. The
// existing `AllUsersResponse` in `lib/types.ts` types `accepted` as `User[]`,
// which is missing fields the table needs (`personal_name`, `account_type`,
// `groups`, etc.), so we declare an accurate local type here.
interface FullUserSnapshot {
  id: string;
  email: string;
  role: UserRole;
  account_type: AccountType;
  is_active: boolean;
  password_configured: boolean;
  personal_name: string | null;
  created_at: string;
  updated_at: string;
  groups: UserGroupInfo[];
  is_scim_synced: boolean;
}

interface ManageUsersResponse {
  accepted: FullUserSnapshot[];
  invited: { email: string }[];
  slack_users: FullUserSnapshot[];
  accepted_pages: number;
  invited_pages: number;
  slack_users_pages: number;
}

function snapshotToMemberRow(snapshot: FullUserSnapshot): MemberRow {
  return {
    id: snapshot.id,
    email: snapshot.email,
    role: snapshot.role,
    status: snapshot.is_active ? UserStatus.ACTIVE : UserStatus.INACTIVE,
    is_active: snapshot.is_active,
    is_scim_synced: snapshot.is_scim_synced,
    personal_name: snapshot.personal_name,
    created_at: snapshot.created_at,
    updated_at: snapshot.updated_at,
    groups: snapshot.groups,
  };
}

function serviceAccountToMemberRow(
  snapshot: FullUserSnapshot,
  apiKey: ApiKeyDescriptor | undefined
): MemberRow {
  return {
    id: snapshot.id,
    email: "Service Account",
    role: apiKey?.api_key_role ?? snapshot.role,
    status: UserStatus.ACTIVE,
    is_active: true,
    is_scim_synced: false,
    personal_name:
      apiKey?.api_key_name ?? snapshot.personal_name ?? "Unnamed Key",
    created_at: null,
    updated_at: null,
    groups: [],
    api_key_display: apiKey?.api_key_display,
  };
}

interface UseGroupMemberCandidatesResult {
  /** Active users + service-account rows, in the order the table expects. */
  rows: MemberRow[];
  /** Subset of `rows` representing real (non-service-account) users. */
  userRows: MemberRow[];
  isLoading: boolean;
  error: unknown;
}

/**
 * Returns the candidate list for the group create/edit member pickers.
 *
 * Hits `/api/manage/users?include_api_keys=true`, which is gated by
 * `current_curator_or_admin_user` on the backend, so this works for both
 * admins and global curators (the admin-only `/accepted/all` and `/invited`
 * endpoints used to be called here, which 403'd for global curators and broke
 * the Edit Group page entirely).
 *
 * For admins, we additionally fetch `/admin/api-key` to enrich service-account
 * rows with the masked api-key display string. That call is admin-only and is
 * skipped for curators; its failure is non-fatal.
 */
export default function useGroupMemberCandidates(): UseGroupMemberCandidatesResult {
  const { isAdmin } = useUser();

  const {
    data: usersData,
    isLoading: usersLoading,
    error: usersError,
  } = useSWR<ManageUsersResponse>(
    SWR_KEYS.groupMemberCandidates,
    errorHandlingFetcher
  );

  const { data: apiKeys, isLoading: apiKeysLoading } = useSWR<
    ApiKeyDescriptor[]
  >(isAdmin ? SWR_KEYS.adminApiKeys : null, errorHandlingFetcher);

  const apiKeysByUserId = useMemo(() => {
    const map = new Map<string, ApiKeyDescriptor>();
    for (const key of apiKeys ?? []) map.set(key.user_id, key);
    return map;
  }, [apiKeys]);

  const { rows, userRows } = useMemo(() => {
    const accepted = usersData?.accepted ?? [];
    const userRowsLocal: MemberRow[] = [];
    const serviceAccountRows: MemberRow[] = [];
    for (const snapshot of accepted) {
      if (!snapshot.is_active) continue;
      if (snapshot.account_type === AccountType.SERVICE_ACCOUNT) {
        serviceAccountRows.push(
          serviceAccountToMemberRow(snapshot, apiKeysByUserId.get(snapshot.id))
        );
      } else {
        userRowsLocal.push(snapshotToMemberRow(snapshot));
      }
    }
    return {
      rows: [...userRowsLocal, ...serviceAccountRows],
      userRows: userRowsLocal,
    };
  }, [usersData, apiKeysByUserId]);

  return {
    rows,
    userRows,
    isLoading: usersLoading || (isAdmin && apiKeysLoading),
    error: usersError,
  };
}
