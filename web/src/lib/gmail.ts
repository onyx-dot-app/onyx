import { Credential } from "./connectors/credentials";

export const setupGmailOAuth = async ({
  isAdmin,
}: {
  isAdmin: boolean;
}): Promise<[string | null, string]> => {
  const credentialCreationResponse = await fetch("/api/manage/credential", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      admin_public: isAdmin,
      credential_json: {},
      source: "gmail",
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
    `/api/manage/connector/gmail/authorize/${credential.id}`
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
