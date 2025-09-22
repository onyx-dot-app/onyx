import {
  CredentialBase,
  CredentialWithPrivateKey,
} from "./connectors/credentials";
import { AccessType } from "@/lib/types";
import { TypedFile } from "./connectors/fileTypes";
import {
  CREDENTIAL_NAME,
  CREDENTIAL_SOURCE,
  CREDENTIAL_UPLOADED_FILE,
  CREDENTIAL_FIELD_KEY,
  CREDENTIAL_TYPE_DEFINITION_KEY,
  CREDENTIAL_JSON,
} from "./constants";

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
  formData.append(CREDENTIAL_JSON, JSON.stringify(credential.credential_json));
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
  formData.append(CREDENTIAL_NAME, credential.name || "");
  formData.append(CREDENTIAL_SOURCE, credential.source);
  if (credential.private_key) {
    formData.append(CREDENTIAL_UPLOADED_FILE, credential.private_key.file);
    formData.append(CREDENTIAL_FIELD_KEY, credential.private_key.fieldKey);
    formData.append(
      CREDENTIAL_TYPE_DEFINITION_KEY,
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
      ([key, value]) => key !== CREDENTIAL_NAME && value !== ""
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
      ([key, value]) => key !== CREDENTIAL_NAME && value !== ""
    )
  );
  const formData = new FormData();
  formData.append(CREDENTIAL_NAME, name);
  formData.append(CREDENTIAL_JSON, JSON.stringify(details));
  formData.append(CREDENTIAL_UPLOADED_FILE, privateKey.file);
  formData.append(CREDENTIAL_FIELD_KEY, privateKey.fieldKey);
  formData.append(
    CREDENTIAL_TYPE_DEFINITION_KEY,
    privateKey.typeDefinition.category
  );
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
