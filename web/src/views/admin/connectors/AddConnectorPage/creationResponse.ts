import type { Credential } from "@/lib/connectors/types";

export interface ObjectCreationIdResponse {
  id: number;
  credential: Credential<unknown> | null;
}

export interface ConnectorWithMockCredentialCreationResponse {
  success: boolean;
  message: string | null;
  data: number | null;
  connector_id: number;
}

export type ConnectorCreationResponse =
  | ObjectCreationIdResponse
  | ConnectorWithMockCredentialCreationResponse;

export function getCreatedConnectorId(
  response: ConnectorCreationResponse
): number {
  return "connector_id" in response ? response.connector_id : response.id;
}
