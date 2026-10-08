"use client";

import type { CredentialRef } from "@/lib/credentials/types";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { useTranslations } from "next-intl";
import { useSettings } from "@/lib/settings/hooks";
import useCCPairs from "@/hooks/useCCPairs";
import { checkCredentialBinding } from "@/lib/connectors/svc";
import {
  bindingCheckInput,
  decideBindingGate,
  type BindingCheckState,
  type BindingGate,
  type BindingGateReason,
  type BoundFieldState,
  type CredentialBindingFieldError,
} from "@/lib/connectors/bindingGate";
import { errorHandlingFetcher } from "@/lib/fetcher";
import { SWR_KEYS } from "@/lib/swr-keys";
import type { FederatedConnectorDetail } from "@/lib/types";
import type { CredentialSchemaResponse } from "@/lib/credentials/types";
import type {
  ConfigurableSources,
  ValidSources,
} from "@/lib/connectors/types/source";

/** The workspace's federated connectors. */
export function useFederatedConnectors() {
  const { mutate } = useSWRConfig();
  const url = SWR_KEYS.federatedConnectors;
  const swrResponse = useSWR<FederatedConnectorDetail[]>(
    url,
    errorHandlingFetcher
  );

  return {
    ...swrResponse,
    refreshFederatedConnectors: () => mutate(url),
  };
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

/**
 * Wait this long after a bound field loses focus. Focus that moves between
 * bound fields, or a click that changes a bound value, then sends one check.
 */
const BINDING_CHECK_BLUR_DELAY_MS = 300;
/** Wait this long after the credential changes, for the values it sets. */
const BINDING_CHECK_CREDENTIAL_DELAY_MS = 50;

export interface UseBoundFieldsGateParams {
  source: ValidSources;
  /** A saved credential or a draft; `null` when none is selected. */
  credential: CredentialRef | null;
  /** The credential's `time_updated`. An edit makes older results stale. */
  credentialUpdatedAt: string | null;
  /** A credential is selected, or the source needs none. */
  credentialSelected: boolean;
  /** Every credential-bound field of the source; the check sends their values. */
  boundFieldNames: string[];
  /** The visible bound fields, as the gate reads them. */
  boundFields: BoundFieldState[];
  values: Record<string, unknown>;
  /** One more condition, applied after the binding passes. */
  extra?: BindingGate;
}

export interface UseBoundFieldsGateResult extends BindingGate {
  /** Bound field name to the backend's error for the current input. */
  fieldErrors: Record<string, CredentialBindingFieldError>;
  /** Checks the current input again, e.g. when a bound field loses focus. */
  requestCheck: () => void;
}

interface BindingCheckResult {
  key: string;
  state: BindingCheckState;
}

/**
 * Whether the create form's configuration is unlocked. It checks the
 * credential and the credential-bound values with the backend when a bound
 * field loses focus or the credential changes, not on each change of a value:
 * each check reads the credential, which writes an audit event. A response
 * for an older input is ignored.
 */
export function useBoundFieldsGate({
  source,
  credential,
  credentialUpdatedAt,
  credentialSelected,
  boundFieldNames,
  boundFields,
  values,
  extra,
}: UseBoundFieldsGateParams): UseBoundFieldsGateResult {
  // A string, so effects follow the credential rather than the object.
  const credentialKey: string | null =
    credential === null ? null : JSON.stringify(credential);
  const { key: inputKey, config } = bindingCheckInput(
    credentialKey,
    boundFieldNames,
    values
  );
  // A result for another source or an older version of the credential is
  // stale too.
  const key = JSON.stringify({ source, inputKey, credentialUpdatedAt });
  const ready =
    boundFields.length > 0 &&
    credential !== null &&
    boundFields.every((field) => !field.missing && !field.invalid);

  const [result, setResult] = useState<BindingCheckResult | null>(null);
  const resultRef = useRef(result);
  const latestRef = useRef({ key, config, credential, ready });
  useEffect(() => {
    latestRef.current = { key, config, credential, ready };
  });

  // Bumped by every scheduled check and on unmount; an older response is
  // ignored.
  const generationRef = useRef(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const setResultFor = useCallback(
    (resultKey: string, state: BindingCheckState) => {
      const next = { key: resultKey, state };
      resultRef.current = next;
      setResult(next);
    },
    []
  );

  const send = useCallback(() => {
    const latest = latestRef.current;
    if (!latest.ready || latest.credential === null) return;
    const generation = ++generationRef.current;
    const update = (state: BindingCheckState) => {
      if (generation === generationRef.current) {
        setResultFor(latest.key, state);
      }
    };
    update({ kind: "checking" });
    checkCredentialBinding(latest.credential, {
      source,
      connector_specific_config: latest.config,
    }).then(
      (response) => update({ kind: "done", response }),
      () => update({ kind: "unavailable" })
    );
  }, [source, setResultFor]);

  // Every blur and credential change checks again: the source may have
  // changed, and a failed request must not stick.
  const schedule = useCallback(
    (delayMs: number) => {
      const latest = latestRef.current;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
      if (latest.ready) {
        // Shown at once; a response for an older input is dropped.
        generationRef.current += 1;
        setResultFor(latest.key, { kind: "checking" });
      }
      timerRef.current = setTimeout(() => {
        timerRef.current = null;
        send();
      }, delayMs);
    },
    [send, setResultFor]
  );

  useEffect(() => {
    if (credentialKey === null) return;
    schedule(BINDING_CHECK_CREDENTIAL_DELAY_MS);
  }, [credentialKey, credentialUpdatedAt, schedule]);

  useEffect(
    () => () => {
      generationRef.current += 1;
      if (timerRef.current !== null) clearTimeout(timerRef.current);
    },
    []
  );

  const requestCheck = useCallback(
    () => schedule(BINDING_CHECK_BLUR_DELAY_MS),
    [schedule]
  );

  const binding: BindingCheckState =
    credential === null
      ? { kind: credentialSelected ? "unavailable" : "idle" }
      : result !== null && result.key === key
        ? result.state
        : { kind: "idle" };
  const gate = decideBindingGate({
    hasBoundFields: boundFields.length > 0,
    credentialSelected,
    boundFields,
    binding,
    extra,
  });
  return {
    ...gate,
    fieldErrors: binding.kind === "done" ? binding.response.field_errors : {},
    requestCheck,
  };
}

/** The line the locked configuration shows, or `null` when it is unlocked. */
export function useBindingGateMessage(
  reason: BindingGateReason | null
): string | null {
  const t = useTranslations("admin.connectorsList");
  if (reason === null) return null;
  switch (reason.kind) {
    case "enterField":
      return t("bindingGate.enterField", { field: reason.label });
    case "fixField":
      return t("bindingGate.fixField", { field: reason.label });
    case "selectCredential":
      return t("credentialRequired.tooltip");
    case "awaitingCheck":
      return t("bindingGate.awaitingCheck");
    case "checking":
      return t("bindingGate.checking");
    case "fieldRejected":
      return reason.error.kind === "missing"
        ? t("bindingGate.enterField", { field: reason.label })
        : t("bindingGate.fieldInvalid", {
            field: reason.label,
            detail: reason.error.detail,
          });
    case "rejected":
      return t("bindingGate.rejected", { detail: reason.rejection.detail });
    case "custom":
      return reason.message;
  }
}
