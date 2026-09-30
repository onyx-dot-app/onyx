"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR, { mutate } from "swr";
import { useTranslations } from "next-intl";
import { useFederatedConnectors, usePublicCredentials } from "@/lib/hooks";
import { useSettings } from "@/lib/settings/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import { credentialTemplates } from "@/lib/connectors/credentials";
import { getConnectorOauthRedirectUrl } from "@/lib/connectors/svc";
import { deleteCredential } from "@/lib/credential";
import {
  CredentialCreationMethod,
  getCredentialCreationMethods,
  shouldRedirectToOAuth,
} from "@/lib/credentials/credentialCreation";
import type { CredentialFieldValues } from "@/lib/credentials/types";
import { getSourceDisplayName, getSourceMetadata } from "@/lib/sources";
import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";
import {
  EE_ENABLED,
  NEXT_PUBLIC_CLOUD_ENABLED,
  NEXT_PUBLIC_TEST_ENV,
} from "@/lib/constants";
import { oauthSupportedSources } from "@/lib/types";
import type {
  AnyCredential,
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
  CredentialSetup,
  OAuthDetails,
  SourceCredentialsResult,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ConfigurableSources,
  CredentialSchemaResponse,
  FederatedConnectorDetail,
  ValidSources,
} from "@/lib/types";

/** How often the credential lists re-poll, in milliseconds. */
const CREDENTIALS_REFRESH_INTERVAL_MS = 5000;

/** The OAuth capabilities of a source: whether it supports OAuth, manual credentials, and any extra fields. */
export function useOAuthDetails(sourceType: ValidSources) {
  return useSWR<OAuthDetails>(
    SWR_KEYS.connectorOAuthDetails(sourceType),
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
  sourceType: ValidSources
): SourceCredentialsResult {
  return useSWR<AnyCredential[], Error>(
    SWR_KEYS.similarCredentials(sourceType),
    errorHandlingFetcher,
    { refreshInterval: CREDENTIALS_REFRESH_INTERVAL_MS }
  );
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
  const { data: credentials } = useSourceCredentials(sourceType);
  const { data: oauthDetails, isLoading } = useOAuthDetails(sourceType);
  const [openMethod, setOpenMethod] = useState<CredentialCreationMethod | null>(
    null
  );
  const [isAuthorizing, setIsAuthorizing] = useState(false);

  const displayName = getSourceDisplayName(sourceType) || sourceType;
  const methods = getCredentialCreationMethods(oauthDetails);
  const template = credentialTemplates[sourceType] as
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

  function refresh() {
    refreshSourceCredentials(sourceType);
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
      response = await deleteCredential(credential.id, true);
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
    oauthDetails,
    isLoading,
    methods,
    namesMethods: methods.length > 1,
    template,
    canAuthorize,
    openMethod,
    open,
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

/**
 * The source types this workspace has connected — indexed connectors first,
 * then federated ones.
 *
 * Reads `vectorDbEnabled` itself, so callers do not thread it. With the vector
 * DB off, `useCCPairs` skips its fetch and the list is federated-only.
 *
 * The array is deliberately neither deduplicated nor sorted. Callers that
 * want one entry per source type run the result through
 * `getConfiguredSources`, which dedups on the cleaned name.
 *
 * `error` is set when either request failed, so the list is short rather than
 * genuinely empty. A caller that hides controls on an empty list should check
 * it, otherwise a failed fetch is indistinguishable from a workspace with
 * nothing connected.
 */
export function useAvailableSources(): {
  availableSources: ValidSources[];
  isLoading: boolean;
  /**
   * Whether the roster is complete: every constituent fetch holds a
   * snapshot, stale allowed. A nonempty array is no proof of this — one
   * constituent can fail its first load while the other returns — so
   * callers resolving a selection must gate on this, not on length.
   */
  settled: boolean;
  error: unknown;
} {
  // `vectorDbEnabled` reads false while settings load, which would make
  // `useCCPairs` skip its fetch and report ready. Wait for settings first, or
  // a cached federated list alone would look like the complete set.
  const { vectorDbEnabled, isLoading: settingsLoading } = useSettings();
  const {
    ccPairs,
    isLoading: ccPairsLoading,
    hasLoaded: ccPairsHasLoaded,
    error: ccPairsError,
  } = useCCPairs(vectorDbEnabled);
  const {
    data: federatedConnectors,
    isLoading: federatedLoading,
    error: federatedError,
  } = useFederatedConnectors();

  const availableSources = useMemo(
    () => [
      ...ccPairs.map((ccPair) => ccPair.source),
      ...(federatedConnectors?.map((connector) => connector.source) ?? []),
    ],
    [ccPairs, federatedConnectors]
  );

  return {
    availableSources,
    isLoading: settingsLoading || ccPairsLoading || federatedLoading,
    settled:
      !settingsLoading && ccPairsHasLoaded && federatedConnectors !== undefined,
    error: ccPairsError ?? federatedError,
  };
}

export const useGmailCredentials = (connector: string) => {
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

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
  const { data: credentialsData } = usePublicCredentials();

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

interface UseFederatedConnectorResult {
  sourceType: ConfigurableSources | null;
  connectorData: FederatedConnectorDetail | null;
  credentialSchema: CredentialSchemaResponse | null;
  isLoading: boolean;
  error: string | null;
}

export function useFederatedConnector(
  connectorId: string
): UseFederatedConnectorResult {
  const t = useTranslations("admin.federated");
  const [sourceType, setSourceType] = useState<ConfigurableSources | null>(
    null
  );
  const [connectorData, setConnectorData] =
    useState<FederatedConnectorDetail | null>(null);
  const [credentialSchema, setCredentialSchema] =
    useState<CredentialSchemaResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        setIsLoading(true);
        setError(null);

        // First, fetch connector details to get the source type
        const connectorResponse = await fetch(`/api/federated/${connectorId}`);

        if (!connectorResponse.ok) {
          throw new Error(
            `Failed to fetch connector: ${connectorResponse.statusText}`
          );
        }

        const connectorData: FederatedConnectorDetail =
          await connectorResponse.json();

        // Extract source type from the federated source string (remove 'federated_' prefix)
        const extractedSourceType = connectorData.source.replace(
          /^federated_/,
          ""
        ) as ConfigurableSources;

        // Now fetch credential schema and set state in parallel
        const schemaPromise = fetch(
          `/api/federated/sources/federated_${extractedSourceType}/credentials/schema`
        );

        // Set the data we already have
        setConnectorData(connectorData);
        setSourceType(extractedSourceType);

        // Wait for schema fetch to complete
        const schemaResponse = await schemaPromise;

        if (!schemaResponse.ok) {
          throw new Error(
            `Failed to fetch schema: ${schemaResponse.statusText}`
          );
        }

        const schemaData: CredentialSchemaResponse =
          await schemaResponse.json();
        setCredentialSchema(schemaData);
      } catch (error) {
        console.error("Error fetching federated connector data:", error);
        setError(t("error.loadFailed", { details: String(error) }));
      } finally {
        setIsLoading(false);
      }
    };

    if (connectorId) {
      fetchData();
    }
  }, [connectorId, t]);

  return {
    sourceType,
    connectorData,
    credentialSchema,
    isLoading,
    error,
  };
}

interface ConnectorGroupRestrictionsStatus {
  enabled: boolean;
}

/**
 * Whether connector forms offer the data-access group restriction. Set by the
 * workspace toggle in Security and Hardening. Fails closed: hidden until the
 * setting loads, and hidden if the request fails.
 */
export function useConnectorGroupRestrictionsEnabled(): boolean {
  const { data } = useSWR<ConnectorGroupRestrictionsStatus>(
    SWR_KEYS.connectorGroupRestrictions,
    errorHandlingFetcher
  );
  return data?.enabled ?? false;
}
