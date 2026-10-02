"use client";

import { useState } from "react";
import { useMessages } from "next-intl";
import useSWR, { mutate, useSWRConfig } from "swr";
import { CREDENTIAL_TEMPLATES } from "@/lib/credentials/constants";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { adminDeleteCredential, deleteCredential } from "@/lib/credentials/svc";
import { usePermissionAuthority } from "@/lib/permissions/hooks";
import { Permission } from "@/lib/types";
import {
  getCredentialCreationMethods,
  shouldRedirectToOAuth,
  titleFromCredentialKey,
} from "@/lib/credentials/utils";
import { CredentialCreationMethod } from "@/lib/credentials/types";
import { getSourceDisplayName, getSourceMetadata } from "@/lib/sources";
import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";
import {
  EE_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import {
  oauthSupportedSources,
  ValidSources,
} from "@/lib/connectors/types/source";
import type {
  AnyCredential,
  Credential,
  CredentialFieldValues,
  CredentialSetup,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
  OAuthDetails,
  SourceCredentialsResult,
} from "@/lib/credentials/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";

/** A credential field's title, and its hint when it has one. */
export interface CredentialFieldCopy {
  title: string;
  description?: string;
}

function hasOwnKey<T extends object>(
  object: T,
  key: string
): key is Extract<keyof T, string> {
  return Object.prototype.hasOwnProperty.call(object, key);
}

/**
 * Looks up a credential field's title and hint in the message catalog
 * (`admin.credentials.fields.<key>`), keyed by the field's credential key.
 * A key the catalog does not list yet falls back to a title read from the
 * key itself, so a new connector's fields never render blank.
 */
export function useCredentialFieldCopy(): (key: string) => CredentialFieldCopy {
  const fields = useMessages().admin.credentials.fields;
  return (key) =>
    hasOwnKey(fields, key)
      ? fields[key]
      : { title: titleFromCredentialKey(key) };
}

/**
 * Every credential the admin can see, across all sources. Pass
 * `enabled: false` to skip the request on pages that do not need it.
 */
export function useAdminCredentials({
  enabled = true,
}: { enabled?: boolean } = {}) {
  const { mutate } = useSWRConfig();
  const swrResponse = useSWR<Credential<any>[]>(
    enabled ? SWR_KEYS.adminCredentials : null,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshCredentials: () => mutate(SWR_KEYS.adminCredentials),
  };
}

/** How often the credential lists re-poll, in milliseconds. */
const CREDENTIALS_REFRESH_INTERVAL_MS = 5000;

interface CredentialFetchOptions {
  /** Fetch only when true. A source with no credentials skips both requests. @default true */
  enabled?: boolean;
}

/** The OAuth capabilities of a source: whether it supports OAuth, manual credentials, and any extra fields. */
export function useOAuthDetails(
  sourceType: ValidSources,
  { enabled = true }: CredentialFetchOptions = {}
) {
  return useSWR<OAuthDetails>(
    enabled ? SWR_KEYS.connectorOAuthDetails(sourceType) : null,
    errorHandlingFetcher,
    {
      shouldRetryOnError: false,
    }
  );
}

/**
 * Every credential this admin can see for one source, refreshed on a timer
 * so a credential created elsewhere appears without a reload.
 *
 * The endpoint already filters by permission, so everything it returns is
 * the caller's to edit or delete; there is no narrower "editable" list.
 */
export function useSourceCredentials(
  sourceType: ValidSources,
  { enabled = true }: CredentialFetchOptions = {}
): SourceCredentialsResult {
  return useSWR<AnyCredential[], Error>(
    enabled ? SWR_KEYS.similarCredentials(sourceType) : null,
    errorHandlingFetcher,
    { refreshInterval: CREDENTIALS_REFRESH_INTERVAL_MS }
  );
}

/**
 * Whether a source's saved credentials and OAuth details have loaded: one
 * verdict for both fetches. Only the credentials can fail it, and only if
 * they never loaded; a later refresh that fails keeps what is shown. OAuth
 * details that fail to load count as loaded without OAuth, so the source
 * still offers manual setup. Disabled, it fetches nothing and reports
 * neither loading nor failed.
 */
export function useCredentialLoad(
  sourceType: ValidSources,
  options: CredentialFetchOptions = {}
) {
  const { data: credentials, error: credentialsError } = useSourceCredentials(
    sourceType,
    options
  );
  const { data: oauthDetails, error: oauthDetailsError } = useOAuthDetails(
    sourceType,
    options
  );
  const enabled = options.enabled ?? true;

  const error: Error | undefined =
    credentials === undefined ? credentialsError : undefined;
  const oauthDetailsSettled =
    oauthDetails !== undefined || oauthDetailsError !== undefined;
  const isLoading =
    enabled &&
    error === undefined &&
    (credentials === undefined || !oauthDetailsSettled);

  return { credentials, oauthDetails, isLoading, error };
}

/**
 * Everything one source needs in order to be authenticated against: its
 * saved credentials, the ways it accepts a new one, the fields each way
 * asks for, and the actions that open, create, delete or authorize.
 *
 * It replaces the set of fetches, lookups and half-duplicated handlers that
 * every screen touching credentials used to assemble for itself.
 *
 * It renders nothing and says nothing. Actions resolve to an error message
 * or `null`, so each screen keeps its own copy and decides whether a failure
 * is a toast, a banner or inline text.
 */
export function useCredentialSetup(sourceType: ValidSources): CredentialSetup {
  const { credentials, oauthDetails, isLoading, error } =
    useCredentialLoad(sourceType);
  const { isGlobalHolder } = usePermissionAuthority(
    Permission.MANAGE_CONNECTORS
  );
  const [openMethod, setOpenMethod] = useState<CredentialCreationMethod | null>(
    null
  );
  const [isAuthorizing, setIsAuthorizing] = useState(false);

  const displayName = getSourceDisplayName(sourceType) || sourceType;
  const methods = getCredentialCreationMethods(oauthDetails);
  const template = CREDENTIAL_TEMPLATES[sourceType] as
    | CredentialFieldValues
    | undefined;

  // Two gates used to be kept apart and could disagree: the source list and
  // the source's own metadata flag. A source has to pass both.
  const canAuthorize =
    EE_ENABLED &&
    (NEXT_PUBLIC_CLOUD_ENABLED || NEXT_PUBLIC_TEST_ENV) &&
    oauthSupportedSources.some((source) => source === sourceType) &&
    getSourceMetadata(sourceType).oauthSupported === true;

  function close() {
    setOpenMethod(null);
  }

  function selectMethod(method: CredentialCreationMethod) {
    setOpenMethod(method);
  }

  function refresh() {
    refreshSourceCredentials(sourceType);
    // The Gmail and Drive setups read the all-source list; keep it in step.
    mutate(SWR_KEYS.adminCredentials);
  }

  async function open(
    method: CredentialCreationMethod
  ): Promise<string | null> {
    // A source that asks for nothing extra has no form to show: the whole
    // flow is the trip to the provider.
    if (method === CredentialCreationMethod.OAuth && oauthDetails) {
      if (shouldRedirectToOAuth(oauthDetails)) {
        try {
          window.location.href = await getConnectorOauthRedirectUrl(
            sourceType,
            {}
          );
        } catch (error) {
          return errorMessage(error);
        }
        return null;
      }
    } else if (method === CredentialCreationMethod.OAuth) {
      // The details have not landed, so there is nothing to build a form from.
      return null;
    }
    setOpenMethod(method);
    return null;
  }

  async function remove(
    credential: AnyCredential,
    failureMessage: string
  ): Promise<string | null> {
    let response: Response;
    try {
      // A global connector manager sees every credential and deletes any of
      // them through the admin route. A scoped manager may not use that
      // route; they delete through the owner route, which covers their own.
      response = isGlobalHolder
        ? await adminDeleteCredential(credential.id)
        : await deleteCredential(credential.id);
    } catch (error) {
      // The request never landed, so nothing changed and nothing refreshes.
      return errorMessage(error) || failureMessage;
    }
    refresh();
    if (response.ok) return null;
    // A failure always answers with something the caller can show: an empty
    // or unreadable body must not read as success.
    try {
      const body = await response.json();
      return body.detail || body.message || failureMessage;
    } catch {
      return failureMessage;
    }
  }

  async function authorize(invalidUrlMessage: string): Promise<string | null> {
    setIsAuthorizing(true);
    try {
      // Read at call time: the page can change its own query string, and a
      // click only ever happens in the browser.
      const response = await prepareOAuthAuthorizationRequest(
        sourceType,
        window.location.href,
        invalidUrlMessage
      );
      if (!response.url) return invalidUrlMessage;
      window.open(response.url, "_blank", "noopener,noreferrer");
      return null;
    } catch (error) {
      return errorMessage(error);
    } finally {
      setIsAuthorizing(false);
    }
  }

  return {
    displayName,
    credentials,
    error,
    oauthDetails,
    isLoading,
    methods,
    namesMethods: methods.length > 1,
    template,
    canAuthorize,
    openMethod,
    open,
    selectMethod,
    close,
    remove,
    refresh,
    authorize,
    isAuthorizing,
  };
}

/** The message on a thrown error, or `""` when it carried none. */
function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "";
}

/** Re-fetches what {@link useSourceCredentials} holds for one source. */
export function refreshSourceCredentials(
  sourceType: ValidSources
): Promise<AnyCredential[] | undefined> {
  return mutate(SWR_KEYS.similarCredentials(sourceType));
}

export const useGmailCredentials = (connector: string) => {
  // Only the Gmail setup reads the admin list; other sources skip it.
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = useAdminCredentials({ enabled: connector === ValidSources.Gmail });

  const gmailPublicCredential: Credential<GmailCredentialJson> | undefined =
    credentialsData?.find(
      (credential) =>
        credential.credential_json?.google_tokens &&
        credential.admin_public &&
        credential.source === connector
    );

  const gmailServiceAccountCredential:
    | Credential<GmailServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.admin_public &&
      credential.source === connector
  );

  const liveGmailCredential =
    gmailPublicCredential || gmailServiceAccountCredential;

  return {
    liveGmailCredential: liveGmailCredential,
  };
};

export const useGoogleDriveCredentials = (connector: string) => {
  // Only the Google Drive setup reads the admin list; other sources skip it.
  const { data: credentialsData } = useAdminCredentials({
    enabled: connector === ValidSources.GoogleDrive,
  });

  const googleDrivePublicCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_tokens &&
      credential.admin_public &&
      credential.source === connector
  );

  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_service_account_key &&
      credential.admin_public &&
      credential.source === connector
  );

  const liveGDriveCredential =
    googleDrivePublicCredential || googleDriveServiceAccountCredential;

  return {
    liveGDriveCredential: liveGDriveCredential,
  };
};

export const useGoogleCredentials = (
  source: ValidSources.Gmail | ValidSources.GoogleDrive
): SourceCredentialsResult => useSourceCredentials(source);
