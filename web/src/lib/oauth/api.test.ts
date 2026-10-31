import { initiateOAuthFlow } from "@/lib/oauth/api";

const location = { href: "https://onyx.example.com/app" };

beforeEach(() => {
  location.href = "https://onyx.example.com/app";
  Object.defineProperty(globalThis, "window", {
    value: { location },
    configurable: true,
  });
});

afterEach(() => {
  jest.restoreAllMocks();
});

test.each(["javascript:alert(1)", "data:text/html,test", "//example.com/auth"])(
  "rejects an unsafe authorization URL: %s",
  async (authorizationUrl) => {
    jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ authorization_url: authorizationUrl, state: "test" })
        )
      );
    await expect(
      initiateOAuthFlow(1, "/app", "Localized invalid authorization URL")
    ).rejects.toThrow("Localized invalid authorization URL");
    expect(location.href).toBe("https://onyx.example.com/app");
    jest.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          authorization_url: "https://example.com/auth",
          state: "test",
        })
      )
    );
    await initiateOAuthFlow(1, "/app", "Localized invalid authorization URL");
    expect(location.href).toBe("https://example.com/auth");
  }
);
