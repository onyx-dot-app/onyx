/*
 * Despite the /manage path, readable by any chat-accessible user, not just admins
 * (backend/onyx/server/documents/connector.py).
 */
import { apiFetch } from "@/api/client";
import type { DocumentSource } from "@/chat/sources";

export interface BasicCCPairInfo {
  has_successful_run: boolean;
  source: DocumentSource;
  status: string;
}

export function getConnectorSources(
  signal?: AbortSignal,
): Promise<BasicCCPairInfo[]> {
  return apiFetch<BasicCCPairInfo[]>("/manage/connector-status", { signal });
}

/*
 * Searched live rather than indexed, so these never appear among the cc-pairs — but the picker
 * must still offer them, or `source_type` excludes them and federated retrieval silently stops.
 * `source` arrives prefixed ("federated_slack").
 */
export interface FederatedConnectorStatus {
  id: number;
  source: DocumentSource;
  name: string;
}

export function getFederatedSources(
  signal?: AbortSignal,
): Promise<FederatedConnectorStatus[]> {
  return apiFetch<FederatedConnectorStatus[]>("/federated", { signal });
}
