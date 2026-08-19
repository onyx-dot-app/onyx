import { Credential } from "./connectors/credentials";

export const setupGoogleDriveOAuth = async ({
  isAdmin,
  name,
  appCredential,
}: {
  isAdmin: boolean;
  name: string;
  // OAuth app ({"web": {...}}) to store on the credential.
  appCredential: Record<string, unknown>;
}): Promise<[string | null, string]> => {
  const credentialCreationResponse = await fetch("/api/manage/credential", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      admin_public: isAdmin,
      credential_json: { google_app_credential: appCredential },
      source: "google_drive",
      name: name,
    }),
  });

  if (!credentialCreationResponse.ok) {
    return [
      null,
      `Failed to create credential - ${credentialCreationResponse.status}`,
    ];
  }
  const credential =
    (await credentialCreationResponse.json()) as Credential<{}>;

  const authorizationUrlResponse = await fetch(
    `/api/manage/connector/google-drive/authorize/${credential.id}`
  );
  if (!authorizationUrlResponse.ok) {
    return [
      null,
      `Failed to create credential - ${authorizationUrlResponse.status}`,
    ];
  }

  const authorizationUrlJson = (await authorizationUrlResponse.json()) as {
    auth_url: string;
  };

  return [authorizationUrlJson.auth_url, ""];
};
