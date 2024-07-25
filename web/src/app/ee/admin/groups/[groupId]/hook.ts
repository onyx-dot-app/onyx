import { useUserGroups } from "@/lib/hooks";

export const useSpecificUserGroup = (groupId: string) => {
  const { data, isLoading, error, refreshUserGroups } = useUserGroups();
  const userGroup = data?.find((group) => group.id.toString() === groupId);
  return {
    userGroup,
    isLoading,
    error,
    refreshUserGroup: refreshUserGroups,
  };
};
