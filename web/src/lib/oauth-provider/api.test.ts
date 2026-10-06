import { submitOAuthProviderConsent } from "@/lib/oauth-provider/api";

afterEach(() => jest.restoreAllMocks());

test("sends the explicit decision and returns the validated callback", async () => {
  const fetchMock = jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        redirect_url: "https://client.example/callback?code=one",
      })
    )
  );

  await expect(
    submitOAuthProviderConsent("request", "csrf", "deny")
  ).resolves.toBe("https://client.example/callback?code=one");
  expect(fetchMock).toHaveBeenCalledWith("/api/oauth-provider/consent", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      request_id: "request",
      csrf_token: "csrf",
      decision: "deny",
    }),
  });
});

test.each([
  "javascript:alert(1)",
  "http://untrusted.example/callback",
  "https://user:password@client.example/callback",
  "http://127.0.0.1.attacker.example/callback",
])("rejects an unsafe callback: %s", async (redirectUrl) => {
  jest.spyOn(global, "fetch").mockResolvedValue(
    new Response(
      JSON.stringify({
        redirect_url: redirectUrl,
      })
    )
  );

  await expect(
    submitOAuthProviderConsent("request", "csrf", "allow")
  ).rejects.toThrow("Invalid OAuth provider callback");
});

test("does not navigate after the server rejects consent", async () => {
  jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response("{}", { status: 403 }));

  await expect(
    submitOAuthProviderConsent("request", "csrf", "allow")
  ).rejects.toThrow("OAuth provider consent failed");
});
