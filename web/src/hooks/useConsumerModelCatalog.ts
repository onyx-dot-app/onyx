import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import {
  ConsumerModelCatalog,
  ConsumerModelPreference,
} from "@/lib/consumerModels/types";

export function useConsumerModelCatalog() {
  const { data, error, mutate, isLoading } = useSWR<ConsumerModelCatalog>(
    SWR_KEYS.consumerModelCatalog,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    catalog: data,
    error,
    isLoading,
    refetch: mutate,
  };
}

export function useConsumerModelPreference() {
  const { data, error, mutate, isLoading } = useSWR<ConsumerModelPreference>(
    SWR_KEYS.consumerModelPreference,
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      dedupingInterval: 60000,
    }
  );

  return {
    preference: data,
    error,
    isLoading,
    refetch: mutate,
  };
}
