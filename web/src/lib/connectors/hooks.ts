"use client";

import { useEffect, useMemo, useState } from "react";
import useSWR from "swr";
import { useTranslations } from "next-intl";
import { useFederatedConnectors, usePublicCredentials } from "@/lib/hooks";
import { useSettings } from "@/lib/settings/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import type {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
  OAuthDetails,
} from "@/lib/connectors/types";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type {
  ConfigurableSources,
  CredentialSchemaResponse,
  FederatedConnectorDetail,
  ValidSources,
} from "@/lib/types";

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
