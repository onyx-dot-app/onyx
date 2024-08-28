import { CredentialBase } from "./connectors/credentials";

export async function createCredential(credential: CredentialBase<any>) {
  return await fetch(`/api/manage/credential`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(credential),
  });
}

export async function adminDeleteCredential<T>(credentialId: number) {
  return await fetch(`/api/manage/admin/credential/${credentialId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export async function deleteCredential<T>(
  credentialId: number,
  force?: boolean
) {
  return await fetch(`/api/manage/credential/${credentialId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export async function forceDeleteCredential<T>(
  credentialId: number,
  force?: boolean
) {
  return await fetch(`/api/manage/credential/force/${credentialId}`, {
    method: "DELETE",
    headers: {
      "Content-Type": "application/json",
    },
  });
}

export function linkCredential(
  connectorId: number,
  credentialId: number,
  name?: string,
  isPublic?: boolean,
  groups?: number[]
) {
  return fetch(
    `/api/manage/connector/${connectorId}/credential/${credentialId}`,
    {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        name: name || null,
        is_public: isPublic !== undefined ? isPublic : true,
        groups: groups || null,
      }),
    }
  );
}

export function updateCredential(credentialId: number, newDetails: any) {
  const name = newDetails.name;
  const details = Object.fromEntries(
    Object.entries(newDetails).filter(
      ([key, value]) => key !== "name" && value !== ""
    )
  );
  return fetch(`/api/manage/admin/credentials/${credentialId}`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      name: name,
      credential_json: details,
    }),
  });
}

export function swapCredential(newCredentialId: number, connectorId: number) {
  return fetch(`/api/manage/admin/credentials/swap`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      new_credential_id: newCredentialId,
      connector_id: connectorId,
    }),
  });
}
