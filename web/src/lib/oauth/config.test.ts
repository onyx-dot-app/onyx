import {
  oauthConfigRequest,
  MASKED_OAUTH_CREDENTIAL,
} from "@/lib/oauth/config";
import { oauthTestRequest } from "@/lib/oauth/testConnection";

const fields = {
  authorizationUrl: " https://provider.example/authorize ",
  tokenUrl: " https://provider.example/token ",
  clientId: " client ",
  clientSecret: " secret ",
  scopes: " read, ,write ",
  supportsPkce: true,
};

test("save and test use identical normalized settings", () => {
  const saved = oauthConfigRequest(fields, false);
  expect(saved).toEqual({
    authorization_url: "https://provider.example/authorize",
    token_url: "https://provider.example/token",
    client_id: "client",
    client_secret: "secret",
    scopes: ["read", "write"],
    supports_pkce: true,
  });
  expect(oauthTestRequest(fields)).toEqual(saved);
});

test("only edits treat masked credentials as unchanged", () => {
  const masked = {
    ...fields,
    clientId: MASKED_OAUTH_CREDENTIAL,
    clientSecret: MASKED_OAUTH_CREDENTIAL,
  };
  expect(oauthConfigRequest(masked, true).client_secret).toBe("");
  expect(oauthTestRequest(masked, 17).client_secret).toBeUndefined();
  expect(oauthTestRequest(masked).client_secret).toBe(MASKED_OAUTH_CREDENTIAL);
});
