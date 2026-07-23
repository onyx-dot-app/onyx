import {
  createCustomExternalApp,
  disconnectUserFromApp,
} from "@/app/craft/services/externalAppsService";

describe("createCustomExternalApp", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 17 }),
    });
  });

  it("creates gateway configuration as JSON without a skill bundle", async () => {
    const input = {
      name: "Acme CRM",
      upstream_url_patterns: ["https://api.acme.test/*"],
      auth_template: { Authorization: "Bearer {api_key}" },
      organization_credentials: { api_key: "secret" },
    };

    await createCustomExternalApp(input);

    expect(global.fetch).toHaveBeenCalledWith("/api/build/admin/apps/custom", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
    const request = jest.mocked(global.fetch).mock.calls[0]![1]!;
    expect(request.body).not.toBeInstanceOf(FormData);
    expect(String(request.body)).not.toContain("bundle");
  });

  it("disconnects through the credential deletion endpoint", async () => {
    await disconnectUserFromApp(17);

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/build/apps/17/credentials",
      { method: "DELETE" }
    );
  });
});
