import {
  ConsumerModelCatalog,
  ConsumerModelProfile,
} from "@/lib/consumerModels/types";

export function findConsumerProfile(
  catalog: ConsumerModelCatalog | undefined,
  profileId: string | null | undefined
): ConsumerModelProfile | null {
  if (!catalog) {
    return null;
  }

  const requestedProfile = catalog.profiles.find(
    (profile) => profile.id === profileId
  );
  if (requestedProfile) {
    return requestedProfile;
  }

  return (
    catalog.profiles.find(
      (profile) => profile.id === catalog.default_profile_id
    ) ??
    catalog.profiles[0] ??
    null
  );
}

export function getConsumerProfileLabel(
  catalog: ConsumerModelCatalog | undefined,
  profileId: string | null | undefined
): string {
  return findConsumerProfile(catalog, profileId)?.label ?? "模型";
}
