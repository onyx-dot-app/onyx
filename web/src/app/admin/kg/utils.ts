import { useUser } from "@/components/user/UserProvider";
import { errorHandlingFetcher } from "@/lib/fetcher";
import useSWR from "swr";
import { KGConfig, KGConfigRaw } from "./interfaces";

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

export function sanitizeKGConfig(raw: KGConfigRaw): KGConfig {
  const coverage_start = new Date(raw.coverage_start);

  return {
    ...raw,
    coverage_start,
  };
}
