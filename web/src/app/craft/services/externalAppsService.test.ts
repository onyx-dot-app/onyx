import {
  disconnectUserFromApp,
  startExternalAppOAuth,
} from "@/app/craft/services/externalAppsService";

describe("externalAppsService", () => {
  beforeEach(() => {
    global.fetch = jest.fn().mockResolvedValue({
      ok: true,
      json: async () => ({ id: 17 }),
    });
  });

  it("preserves legacy OAuth start and encodes the optional member return path", async () => {
    await startExternalAppOAuth(17);
    expect(global.fetch).toHaveBeenLastCalledWith(
      "/api/build/apps/17/oauth/start"
    );
    const path =
      "/app/plugins/oauth/complete?pluginKind=external-app&attempt=nonce";
    await startExternalAppOAuth(17, path);
    expect(global.fetch).toHaveBeenLastCalledWith(
      `/api/build/apps/17/oauth/start?${new URLSearchParams({ return_path: path })}`
    );
  });

  it("disconnects through the credential deletion endpoint", async () => {
    await disconnectUserFromApp(17);

    expect(global.fetch).toHaveBeenCalledWith(
      "/api/build/apps/17/credentials",
      { method: "DELETE" }
    );
  });
});
