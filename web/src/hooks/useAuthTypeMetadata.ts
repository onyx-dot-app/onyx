import useSWR from "swr";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { AuthType, NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
  hasUsers: boolean;
  oauthEnabled: boolean;
}

const DEFAULT_AUTH_TYPE_METADATA: AuthTypeMetadata = {
  authType: NEXT_PUBLIC_CLOUD_ENABLED ? AuthType.CLOUD : AuthType.BASIC,
  autoRedirect: false,
  requiresVerification: false,
  anonymousUserEnabled: null,
  passwordMinLength: 0,
  hasUsers: false,
  oauthEnabled: false,
};

export function useAuthTypeMetadata(): {
  authTypeMetadata: AuthTypeMetadata;
  isLoading: boolean;
  error: Error | undefined;
} {
  const { data, error, isLoading } = useSWR<AuthTypeMetadata>(
    "/api/auth/type",
    errorHandlingFetcher,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 30_000,
    }
  );

  if (NEXT_PUBLIC_CLOUD_ENABLED && data) {
    return {
      authTypeMetadata: { ...data, authType: AuthType.CLOUD },
      isLoading,
      error,
    };
  }

  return {
    authTypeMetadata: data ?? DEFAULT_AUTH_TYPE_METADATA,
    isLoading,
    error,
  };
}
