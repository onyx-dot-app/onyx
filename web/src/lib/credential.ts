import {
  CredentialBase,
  CredentialWithPrivateKey,
} from "./connectors/credentials";
import { AccessType } from "@/lib/types";
import { TypedFile } from "./connectors/fileTypes";

export async function createCredential(credential: CredentialBase<any>) {
  return await fetch(`/api/manage/credential`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(credential),
  });
}

export async function createCredentialWithPrivateKey(
  credential: CredentialWithPrivateKey<any>
) {
  const formData = new FormData();
  formData.append(
    "credential_json",
    JSON.stringify(credential.credential_json)
  );
  formData.append("admin_public", credential.admin_public.toString());
  formData.append(
    "curator_public",
    credential.curator_public?.toString() || "false"
  );
  if (credential.groups && credential.groups.length > 0) {
    credential.groups.forEach((group) => {
      formData.append("groups", String(group));
    });
  }
  formData.append("name", credential.name || "");
  formData.append("source", credential.source);
  if (credential.private_key) {
    formData.append("uploaded_file", credential.private_key.file);
    formData.append("field_key", credential.private_key.fieldKey);
    formData.append(
      "type_definition_key",
      credential.private_key.typeDefinition.category
    );
  }
  return await fetch(`/api/manage/credential/private-key`, {
    method: "POST",
    body: formData,
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

export async function forceDeleteCredential<T>(credentialId: number) {
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
  accessType?: AccessType,
  groups?: number[],
  autoSyncOptions?: Record<string, any>
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
        access_type: accessType !== undefined ? accessType : "public",
        groups: groups || null,
        auto_sync_options: autoSyncOptions || null,
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
  return fetch(`/api/manage/admin/credential/${credentialId}`, {
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

export function updateCredentialWithPrivateKey(
  credentialId: number,
  newDetails: any,
  privateKey: TypedFile
) {
  const name = newDetails.name;
  const details = Object.fromEntries(
    Object.entries(newDetails).filter(
      ([key, value]) => key !== "name" && value !== ""
    )
  );
  const formData = new FormData();
  formData.append("name", name);
  formData.append("credential_json", JSON.stringify(details));
  formData.append("uploaded_file", privateKey.file);
  formData.append("field_key", privateKey.fieldKey);
  formData.append("type_definition_key", privateKey.typeDefinition.category);
  return fetch(`/api/manage/admin/credential/private-key/${credentialId}`, {
    method: "PUT",
    body: formData,
  });
}

export function swapCredential(
  newCredentialId: number,
  connectorId: number,
  accessType: AccessType
) {
  return fetch(`/api/manage/admin/credential/swap`, {
    method: "PUT",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      new_credential_id: newCredentialId,
      connector_id: connectorId,
      access_type: accessType,
    }),
  });
}
