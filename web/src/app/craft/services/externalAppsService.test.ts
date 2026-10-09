import {
  createCustomExternalApp,
  disconnectUserFromApp,
  updateExternalApp,
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
  });

  it("disconnects through the credential deletion endpoint", async () => {
    await disconnectUserFromApp(17);

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/build/apps/17/credentials",
      { method: "DELETE" }
    );
  });

  it("sends one complete custom-skill association replacement", async () => {
    await updateExternalApp(17, {
      name: "Acme CRM",
      associated_skill_ids: ["skill-a", "skill-b"],
    });

    expect(global.fetch).toHaveBeenCalledWith("/api/build/admin/apps/17", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: "Acme CRM",
        associated_skill_ids: ["skill-a", "skill-b"],
      }),
    });
  });
});
