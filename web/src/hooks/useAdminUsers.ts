"use client";

import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { UserStatus } from "@/lib/types";
import type { UserRole, InvitedUserSnapshot } from "@/lib/types";
import type {
  UserRow,
  UserGroupInfo,
} from "@/refresh-pages/admin/UsersPage/interfaces";

// ---------------------------------------------------------------------------
// Backend response shape (GET /manage/users/accepted/all)
// ---------------------------------------------------------------------------

interface FullUserSnapshot {
  id: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  password_configured: boolean;
  personal_name: string | null;
  created_at: string;
  updated_at: string;
  groups: UserGroupInfo[];
  is_scim_synced: boolean;
}

// ---------------------------------------------------------------------------
// Converters
// ---------------------------------------------------------------------------

function toUserRow(snapshot: FullUserSnapshot): UserRow {
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

function emailToUserRow(
  email: string,
  status: UserStatus.INVITED | UserStatus.REQUESTED
): UserRow {
  return {
    id: null,
    email,
    role: null,
    status,
    is_active: false,
    is_scim_synced: false,
    personal_name: null,
    created_at: null,
    updated_at: null,
    groups: [],
  };
}

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export default function useAdminUsers() {
  const {
    data: acceptedData,
    isLoading: acceptedLoading,
    mutate: acceptedMutate,
  } = useSWR<FullUserSnapshot[]>(
    "/api/manage/users/accepted/all",
    errorHandlingFetcher
  );

  const {
    data: invitedData,
    isLoading: invitedLoading,
    mutate: invitedMutate,
  } = useSWR<InvitedUserSnapshot[]>(
    "/api/manage/users/invited",
    errorHandlingFetcher
  );

  const {
    data: requestedData,
    isLoading: requestedLoading,
    mutate: requestedMutate,
  } = useSWR<InvitedUserSnapshot[]>(
    NEXT_PUBLIC_CLOUD_ENABLED ? "/api/tenants/users/pending" : null,
    errorHandlingFetcher
  );

  const acceptedRows = (acceptedData ?? []).map(toUserRow);
  const invitedRows = (invitedData ?? []).map((u) =>
    emailToUserRow(u.email, UserStatus.INVITED)
  );
  const requestedRows = (requestedData ?? []).map((u) =>
    emailToUserRow(u.email, UserStatus.REQUESTED)
  );

  const users = [...invitedRows, ...requestedRows, ...acceptedRows];

  const isLoading = acceptedLoading || invitedLoading || requestedLoading;

  function refresh() {
    acceptedMutate();
    invitedMutate();
    requestedMutate();
  }

  return { users, isLoading, refresh };
}
