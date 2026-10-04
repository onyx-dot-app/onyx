import { prepareOAuthAuthorizationRequest } from "@/lib/oauth_utils";

beforeEach(() => {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: { location: new URL("https://onyx.example.com/admin/connectors") },
  });
});

afterEach(() => jest.restoreAllMocks());

test("converts the connector page URL into a site-relative completion path", async () => {
  const fetchMock = jest
    .spyOn(globalThis, "fetch")
    .mockResolvedValue(
      new Response(JSON.stringify({ url: "https://provider.example.com/auth" }))
    );
  await prepareOAuthAuthorizationRequest(
    "slack",
    "https://onyx.example.com/admin/connectors?step=2#settings",
    "Localized invalid completion URL"
  );
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/oauth/prepare-authorization-request?connector=slack&redirect_on_success=%2Fadmin%2Fconnectors%3Fstep%3D2%23settings",
    expect.objectContaining({
      body: JSON.stringify({
        connector: "slack",
        redirect_on_success: "/admin/connectors?step=2#settings",
      }),
    })
  );
});

test.each([
  "https://other.example.com/path",
  "//other.example.com/path",
  "javascript:alert(1)",
])(
  "rejects an external completion URL %s before sending state",
  async (url) => {
    const fetchMock = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ url: "https://provider.example.com/auth" })
        )
      );
    await expect(
      prepareOAuthAuthorizationRequest(
        "slack",
        url,
        "Localized invalid completion URL"
      )
    ).rejects.toThrow("Localized invalid completion URL");
    expect(fetchMock).not.toHaveBeenCalled();
  }
);

test.each([
  "https://onyx.example.com//other.example.com/path",
  "https://onyx.example.com/\\other.example.com/path",
])(
  "rejects an ambiguous same-origin completion path %s before sending state",
  async (url) => {
    const fetchMock = jest
      .spyOn(globalThis, "fetch")
      .mockResolvedValue(
        new Response(
          JSON.stringify({ url: "https://provider.example.com/auth" })
        )
      );
    await expect(
      prepareOAuthAuthorizationRequest(
        "slack",
        url,
        "Localized invalid completion URL"
      )
    ).rejects.toThrow("Localized invalid completion URL");
    expect(fetchMock).not.toHaveBeenCalled();
  }
);
