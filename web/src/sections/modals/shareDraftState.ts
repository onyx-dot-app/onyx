import type { MinimalUserGroupSnapshot } from "@/hooks/useShareableGroups";
import type { MinimalUserSnapshot } from "@/lib/types";
import type { ShareAccessPermission } from "@/sections/modals/shareAccessConstants";

export interface ShareDraftUserShare<
  Permission extends ShareAccessPermission = ShareAccessPermission,
> {
  user: MinimalUserSnapshot;
  permission: Permission;
}

export interface ShareDraftGroupShare<
  Permission extends ShareAccessPermission = ShareAccessPermission,
> {
  group_id: number;
  group_name: string;
  permission: Permission;
}

export interface ShareDraftState<
  Permission extends ShareAccessPermission = ShareAccessPermission,
> {
  groupShares: ShareDraftGroupShare<Permission>[];
  isPublic: boolean;
  publicPermission: Permission;
  userShares: ShareDraftUserShare<Permission>[];
}

export function serializeDraftState<Permission extends ShareAccessPermission>(
  state: ShareDraftState<Permission>
): string {
  const normalizedUsers = [...state.userShares]
    .map((share) => ({ id: share.user.id, permission: share.permission }))
    .sort((first, second) => first.id.localeCompare(second.id));
  const normalizedGroups = [...state.groupShares]
    .map((share) => ({ id: share.group_id, permission: share.permission }))
    .sort((first, second) => first.id - second.id);

  return JSON.stringify({
    groupShares: normalizedGroups,
    isPublic: state.isPublic,
    publicPermission: state.publicPermission,
    userShares: normalizedUsers,
  });
}

export function applyStagedShares<Permission extends ShareAccessPermission>(
  draftState: ShareDraftState<Permission>,
  stagedUsers: MinimalUserSnapshot[],
  stagedGroups: MinimalUserGroupSnapshot[],
  stagedPermission: Permission
): ShareDraftState<Permission> {
  const userShareMap = new Map(
    draftState.userShares.map((share) => [share.user.id, share])
  );
  const groupShareMap = new Map(
    draftState.groupShares.map((share) => [share.group_id, share])
  );

  stagedUsers.forEach((user) => {
    userShareMap.set(user.id, { permission: stagedPermission, user });
  });

  stagedGroups.forEach((group) => {
    groupShareMap.set(group.id, {
      group_id: group.id,
      group_name: group.name,
      permission: stagedPermission,
    });
  });

  return {
    ...draftState,
    groupShares: Array.from(groupShareMap.values()),
    userShares: Array.from(userShareMap.values()),
  };
}
