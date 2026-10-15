import { externalAppToConnectable } from "@/app/craft/v1/apps/connectableApps";
import { getOAuthAuthorizationUrl } from "@/lib/oauth/api";
import { startExternalAppOAuth } from "@/app/craft/services/externalAppsService";
import { appFixture } from "@/lib/skills/__fixtures__/picker";

jest.mock("@/lib/oauth/api");
jest.mock("@/app/craft/services/externalAppsService");

describe("externalAppToConnectable", () => {
  beforeEach(() => jest.clearAllMocks());

  it("uses the source OAuth configuration for a linked app", async () => {
    jest
      .mocked(getOAuthAuthorizationUrl)
      .mockResolvedValue("https://provider.example/auth");
    const app = externalAppToConnectable(
      appFixture({
        id: 42,
        app_type: "CUSTOM",
        supports_oauth: true,
        oauth_config_id: 7,
      })
    );
    expect(app.connectMode).toBe("oauth");
    await expect(app.startOAuth()).resolves.toBe(
      "https://provider.example/auth"
    );
    expect(getOAuthAuthorizationUrl).toHaveBeenCalledWith(
      7,
      "/craft/v1/apps?oauthConnectedAppId=42"
    );
    expect(startExternalAppOAuth).not.toHaveBeenCalled();
  });

  it("keeps built-in apps on their provider OAuth flow", async () => {
    jest
      .mocked(startExternalAppOAuth)
      .mockResolvedValue({ authorize_url: "https://provider.example/auth" });
    const app = externalAppToConnectable(
      appFixture({ id: 42, app_type: "SLACK", supports_oauth: true })
    );
    await app.startOAuth();
    expect(startExternalAppOAuth).toHaveBeenCalledWith(42);
    expect(getOAuthAuthorizationUrl).not.toHaveBeenCalled();
  });
});
