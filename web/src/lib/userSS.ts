import { cookies } from "next/headers";
import { User } from "./types";
import { buildUrl, UrlBuilder } from "./utilsSS";
import { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";
import { AuthType, NEXT_PUBLIC_CLOUD_ENABLED } from "./constants";

export interface AuthTypeMetadata {
  authType: AuthType;
  autoRedirect: boolean;
  requiresVerification: boolean;
  anonymousUserEnabled: boolean | null;
  passwordMinLength: number;
}

export const getAuthTypeMetadataSS = async (): Promise<AuthTypeMetadata> => {
  const res = await fetch(buildUrl("/auth/type"));
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: {
    auth_type: string;
    requires_verification: boolean;
    anonymous_user_enabled: boolean | null;
    password_min_length: number;
  } = await res.json();

  let authType: AuthType;

  // Override fastapi users auth so we can use both
  if (NEXT_PUBLIC_CLOUD_ENABLED) {
    authType = AuthType.CLOUD;
  } else {
    authType = data.auth_type as AuthType;
  }

  // for SAML / OIDC, we auto-redirect the user to the IdP when the user visits
  // Onyx in an un-authenticated state
  if (authType === AuthType.OIDC || authType === AuthType.SAML) {
    return {
      authType,
      autoRedirect: true,
      requiresVerification: data.requires_verification,
      anonymousUserEnabled: data.anonymous_user_enabled,
      passwordMinLength: data.password_min_length,
    };
  }
  return {
    authType,
    autoRedirect: false,
    requiresVerification: data.requires_verification,
    anonymousUserEnabled: data.anonymous_user_enabled,
    passwordMinLength: data.password_min_length,
  };
};

export const getAuthDisabledSS = async (): Promise<boolean> => {
  return (await getAuthTypeMetadataSS()).authType === AuthType.DISABLED;
};

const getOIDCAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/oidc/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

const getGoogleOAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/oauth/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString(), {
    headers: {
      cookie: processCookies(await cookies()),
    },
  });
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

const getSAMLAuthUrlSS = async (nextUrl: string | null): Promise<string> => {
  const url = UrlBuilder.fromInternalUrl("/auth/saml/authorize");
  if (nextUrl) {
    url.addParam("next", nextUrl);
  }

  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error("Failed to fetch data");
  }

  const data: { authorization_url: string } = await res.json();
  return data.authorization_url;
};

export const getAuthUrlSS = async (
  authType: AuthType,
  nextUrl: string | null
): Promise<string> => {
  // Returns the auth url for the given auth type

  switch (authType) {
    case AuthType.DISABLED:
      return "";
    case AuthType.BASIC:
      return "";
    case AuthType.GOOGLE_OAUTH: {
      return await getGoogleOAuthUrlSS(nextUrl);
    }
    case AuthType.CLOUD: {
      return await getGoogleOAuthUrlSS(nextUrl);
    }
    case AuthType.SAML: {
      return await getSAMLAuthUrlSS(nextUrl);
    }
    case AuthType.OIDC: {
      return await getOIDCAuthUrlSS(nextUrl);
    }
  }
};

const logoutStandardSS = async (headers: Headers): Promise<Response> => {
  return await fetch(buildUrl("/auth/logout"), {
    method: "POST",
    headers: headers,
  });
};

const logoutSAMLSS = async (headers: Headers): Promise<Response> => {
  return await fetch(buildUrl("/auth/saml/logout"), {
    method: "POST",
    headers: headers,
  });
};

export const logoutSS = async (
  authType: AuthType,
  headers: Headers
): Promise<Response | null> => {
  switch (authType) {
    case AuthType.DISABLED:
      return null;
    case AuthType.SAML: {
      return await logoutSAMLSS(headers);
    }
    default: {
      return await logoutStandardSS(headers);
    }
  }
};

export const getCurrentUserSS = async (): Promise<User | null> => {
  try {
    let cookieString = (await cookies())
      .getAll()
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join("; ");

    // Inject debug auth cookie for local development against remote backend
    if (
      process.env.DEBUG_AUTH_COOKIE &&
      process.env.NODE_ENV === "development"
    ) {
      const debugCookie = `fastapiusersauth=${process.env.DEBUG_AUTH_COOKIE}`;
      cookieString = cookieString
        ? `${cookieString}; ${debugCookie}`
        : debugCookie;
    }

    const response = await fetch(buildUrl("/me"), {
      credentials: "include",
      next: { revalidate: 0 },
      headers: {
        cookie: cookieString,
      },
    });

    if (!response.ok) {
      return null;
    }

    const user = await response.json();
    return user;
  } catch (e) {
    console.log(`Error fetching user: ${e}`);
    return null;
  }
};

export const processCookies = (cookies: ReadonlyRequestCookies): string => {
  let cookieString = cookies
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");

  // Inject debug auth cookie for local development against remote backend
  if (process.env.DEBUG_AUTH_COOKIE && process.env.NODE_ENV === "development") {
    const debugCookie = `fastapiusersauth=${process.env.DEBUG_AUTH_COOKIE}`;
    cookieString = cookieString
      ? `${cookieString}; ${debugCookie}`
      : debugCookie;
  }

  return cookieString;
};
