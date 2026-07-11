"use client";

import { useCallback } from "react";
import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";
import { SWR_KEYS } from "@/lib/swr-keys";
import { UserStatus } from "@/lib/types";
import type { InvitedUserSnapshot } from "@/lib/types";
import type {
  FullUserSnapshot,
  UserRow,
} from "@/views/admin/UsersPage/interfaces";

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
    craft_enabled: snapshot.craft_enabled,
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
    craft_enabled: null,
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
    error: acceptedError,
    mutate: acceptedMutate,
  } = useSWR<FullUserSnapshot[]>(SWR_KEYS.acceptedUsers, errorHandlingFetcher);

  const {
    data: invitedData,
    isLoading: invitedLoading,
    error: invitedError,
    mutate: invitedMutate,
  } = useSWR<InvitedUserSnapshot[]>(
    SWR_KEYS.invitedUsers,
    errorHandlingFetcher
  );

  const {
    data: requestedData,
    isLoading: requestedLoading,
    error: requestedError,
    mutate: requestedMutate,
  } = useSWR<InvitedUserSnapshot[]>(
    NEXT_PUBLIC_CLOUD_ENABLED ? SWR_KEYS.pendingTenantUsers : null,
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
  const error = acceptedError ?? invitedError ?? requestedError;

  const refresh = useCallback(() => {
    acceptedMutate();
    invitedMutate();
    requestedMutate();
  }, [acceptedMutate, invitedMutate, requestedMutate]);

  return { users, isLoading, error, refresh };
}
