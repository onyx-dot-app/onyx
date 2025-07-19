import { useUser } from "@/components/user/UserProvider";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { EntityType } from "./interfaces";

const DEFAULT_CONNECTOR_NAME = "Ungrounded";

export type KgExposedStatus = { kgExposed: boolean; isLoading: boolean };

export function useIsKGExposed(): KgExposedStatus {
  const { isAdmin } = useUser();
  const { data: kgExposedRaw, isLoading } = useSWR<boolean>(
    isAdmin ? "/api/admin/kg/exposed" : null,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateIfStale: false,
      revalidateOnReconnect: false,
    }
  );
  return { kgExposed: kgExposedRaw ?? false, isLoading };
}

export function entityTypesToEntityMap(
  entityTypes: EntityType[]
): Record<string, EntityType[]> {
  return entityTypes.reduce(
    (acc, entityType) => {
      const key = entityType.grounded_source_name
        ? entityType.grounded_source_name
        : DEFAULT_CONNECTOR_NAME;

      if (acc[key]) {
        acc[key].push(entityType);
      } else {
        acc[key] = [entityType];
      }

      return acc;
    },
    {} as Record<string, EntityType[]>
  );
}
