import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { SSOProviderType } from "@/lib/sso/interfaces";
import { CREATABLE_SSO_PROVIDER_TYPES } from "@/lib/sso/utils";

interface SupportedSSOProviderTypes {
  providerTypes: SSOProviderType[];
  isLoading: boolean;
  error?: unknown;
}

// Provider types this deployment can serve, in form display order. Keep the
// picker disabled while loading: an empty list is not yet "none supported".
export function useSupportedSSOProviderTypes(): SupportedSSOProviderTypes {
  const { data, error, isLoading } = useSWR<SSOProviderType[]>(
    SWR_KEYS.adminSsoProviderTypes,
    errorHandlingFetcher
  );

  return {
    // SWR's isLoading is false once the first request settles, error included,
    // so the picker never waits on data that failed to arrive.
    providerTypes: CREATABLE_SSO_PROVIDER_TYPES.filter((type) =>
      (data ?? []).includes(type)
    ),
    isLoading,
    error,
  };
}
