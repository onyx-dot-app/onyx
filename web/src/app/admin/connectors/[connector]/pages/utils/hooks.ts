import { GmailConfig } from "@/lib/connectors/connectors";

export const gmailConnectorNameBuilder = (values: GmailConfig) =>
  "GmailConnector";

import { usePublicCredentials } from "@/lib/hooks";
import {
  Credential,
  GmailCredentialJson,
  GmailServiceAccountCredentialJson,
  GoogleDriveCredentialJson,
  GoogleDriveServiceAccountCredentialJson,
} from "@/lib/connectors/credentials";

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
