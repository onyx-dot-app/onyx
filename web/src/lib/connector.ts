import { Connector, ConnectorBase } from "./connectors/connectors";
async function handleResponse(
  response: Response
): Promise<[string | null, any]> {
  const responseJson = await response.json();
  if (response.ok) {
    return [null, responseJson];
  }
  return [responseJson.detail, null];
}

export async function createConnector<T>(
  connector: ConnectorBase<T>
): Promise<[string | null, Connector<T> | null]> {
  const response = await fetch(`/api/manage/admin/connector`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(connector),
  });
  return handleResponse(response);
}

export async function updateConnectorCredentialPairName(
  ccPairId: number,
  newName: string
): Promise<Response> {
  return fetch(
    `/api/manage/admin/cc-pair/${ccPairId}/name?new_name=${encodeURIComponent(
      newName
    )}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
    }
  );
}

export async function updateConnectorCredentialPairProperty(
  ccPairId: number,
  name: string,
  value: string
): Promise<Response> {
  return fetch(`/api/manage/admin/cc-pair/${ccPairId}/property`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: name,
      value: value,
    }),
  });
}

export async function deleteConnector(
  connectorId: number
): Promise<string | null> {
  const response = await fetch(`/api/manage/admin/connector/${connectorId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
  if (response.ok) {
    return null;
  }
  return (await response.json()).detail;
}

export async function runConnector(
  connectorId: number,
  credentialIds: number[],
  fromBeginning: boolean = false
): Promise<string | null> {
  const response = await fetch("/api/manage/admin/connector/run-once", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      connector_id: connectorId,
      credentialIds,
      from_beginning: fromBeginning,
    }),
  });
  if (!response.ok) {
    return (await response.json()).detail;
  }
  return null;
}
