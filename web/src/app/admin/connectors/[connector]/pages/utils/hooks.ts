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

export const useGmailCredentials = () => {
  const {
    data: credentialsData,
    isLoading: isCredentialsLoading,
    error: credentialsError,
    refreshCredentials,
  } = usePublicCredentials();

  const gmailPublicCredential: Credential<GmailCredentialJson> | undefined =
    credentialsData?.find(
      (credential) =>
        credential.credential_json?.gmail_tokens && credential.admin_public
    );

  const gmailServiceAccountCredential:
    | Credential<GmailServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) => credential.credential_json?.gmail_service_account_key
  );

  const liveGmailCredential =
    gmailPublicCredential || gmailServiceAccountCredential;

  return {
    liveGmailCredential,
  };
};

export const useGoogleDriveCredentials = () => {
  const { data: credentialsData } = usePublicCredentials();

  const googleDrivePublicCredential:
    | Credential<GoogleDriveCredentialJson>
    | undefined = credentialsData?.find(
    (credential) =>
      credential.credential_json?.google_drive_tokens && credential.admin_public
  );

  const googleDriveServiceAccountCredential:
    | Credential<GoogleDriveServiceAccountCredentialJson>
    | undefined = credentialsData?.find(
    (credential) => credential.credential_json?.google_drive_service_account_key
  );

  const liveGDriveCredential =
    googleDrivePublicCredential || googleDriveServiceAccountCredential;

  return {
    liveGDriveCredential,
  };
};
