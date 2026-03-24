import useSWR from "swr";
import { AuthType, NEXT_PUBLIC_CLOUD_ENABLED } from "@/lib/constants";

interface AuthTypeAPIResponse {
  auth_type: string;
  requires_verification: boolean;
  anonymous_user_enabled: boolean | null;
  password_min_length: number;
  has_users: boolean;
  oauth_enabled: boolean;
}

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

async function fetchAuthTypeMetadata(url: string): Promise<AuthTypeMetadata> {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Failed to fetch auth type metadata");
  const data: AuthTypeAPIResponse = await res.json();
  const authType = NEXT_PUBLIC_CLOUD_ENABLED
    ? AuthType.CLOUD
    : (data.auth_type as AuthType);
  return {
    authType,
    autoRedirect: authType === AuthType.OIDC || authType === AuthType.SAML,
    requiresVerification: data.requires_verification,
    anonymousUserEnabled: data.anonymous_user_enabled,
    passwordMinLength: data.password_min_length,
    hasUsers: data.has_users,
    oauthEnabled: data.oauth_enabled,
  };
}

export function useAuthTypeMetadata(): {
  authTypeMetadata: AuthTypeMetadata;
  isLoading: boolean;
  error: Error | undefined;
} {
  const { data, error, isLoading } = useSWR<AuthTypeMetadata>(
    "/api/auth/type",
    fetchAuthTypeMetadata,
    {
      revalidateOnFocus: false,
      revalidateOnReconnect: false,
      dedupingInterval: 30_000,
    }
  );

  return {
    authTypeMetadata: data ?? DEFAULT_AUTH_TYPE_METADATA,
    isLoading,
    error,
  };
}
