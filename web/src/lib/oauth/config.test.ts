import {
  oauthConfigRequest,
  MASKED_OAUTH_CREDENTIAL,
} from "@/lib/oauth/config";

const fields = {
  authorizationUrl: " https://provider.example/authorize ",
  tokenUrl: " https://provider.example/token ",
  clientId: " client ",
  clientSecret: " secret ",
  scopes: " read, ,write ",
  supportsPkce: true,
};

test("normalizes settings shared by save and test", () => {
  const saved = oauthConfigRequest(fields, false);
  expect(saved).toEqual({
    authorization_url: "https://provider.example/authorize",
    token_url: "https://provider.example/token",
    client_id: "client",
    client_secret: "secret",
    scopes: ["read", "write"],
    supports_pkce: true,
  });
});

test("only edits treat masked credentials as unchanged", () => {
  const masked = {
    ...fields,
    clientId: MASKED_OAUTH_CREDENTIAL,
    clientSecret: MASKED_OAUTH_CREDENTIAL,
  };
  expect(oauthConfigRequest(masked, true).client_secret).toBe("");
  expect(oauthConfigRequest(masked, false).client_secret).toBe(
    MASKED_OAUTH_CREDENTIAL
  );
});
