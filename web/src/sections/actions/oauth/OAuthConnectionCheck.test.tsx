import {
  act,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import OAuthConnectionCheck from "@/sections/actions/oauth/OAuthConnectionCheck";
import {
  OAUTH_TEST_MESSAGE_TYPE,
  oauthTestChannelName,
} from "@/lib/oauth/testConnection";

const fields = {
  authorizationUrl: "https://provider.example/authorize",
  tokenUrl: "https://provider.example/token",
  clientId: "draft-client",
  clientSecret: "draft-secret",
  scopes: "read, write",
  supportsPkce: true,
};
function fakePopup() {
  const storage = new Map<string, string>();
  const popup = {
    closed: false,
    close: jest.fn(),
    location: { href: "" },
    sessionStorage: {
      setItem: (key: string, value: string) => storage.set(key, value),
    },
  };
  jest.spyOn(window, "open").mockReturnValue(popup as unknown as Window);
  return { popup, storage };
}
function sendResult(
  source: object,
  state = "test-state",
  origin = window.location.origin
) {
  const event = new MessageEvent("message", {
    origin,
    data: {
      type: OAUTH_TEST_MESSAGE_TYPE,
      state,
      result: { status: "success", supports_pkce: true },
    },
  });
  Object.defineProperty(event, "source", { value: source });
  act(() => window.dispatchEvent(event));
}
function mockEndpoints() {
  return jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    // POST discovery or test/initiate; neither request saves the config.
    if (String(input).endsWith("pkce-support"))
      return new Response(JSON.stringify({ status: "supported" }));
    return new Response(
      JSON.stringify({
        authorization_url:
          "https://provider.example/authorize?state=test-state",
        state: "test-state",
      })
    );
  });
}
afterEach(() => jest.restoreAllMocks());

test("tests unsaved fields and accepts only its popup, origin, and state", async () => {
  const user = setupUser();
  const fetchSpy = mockEndpoints();
  const { popup, storage } = fakePopup();
  render(<OAuthConnectionCheck values={fields} />);
  await user.click(screen.getByRole("button", { name: "Start Checks" }));
  await waitFor(() =>
    expect(popup.location.href).toContain("state=test-state")
  );
  const call = fetchSpy.mock.calls.find(([url]) =>
    String(url).endsWith("test/initiate")
  );
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({
    authorization_url: fields.authorizationUrl,
    token_url: fields.tokenUrl,
    client_id: "draft-client",
    client_secret: "draft-secret",
    scopes: ["read", "write"],
    supports_pkce: true,
  });
  expect([...storage.values()].join(" ")).not.toMatch(
    /draft-secret|draft-client/
  );
  sendResult(window);
  sendResult(popup, "wrong-state");
  sendResult(popup, "test-state", "https://attacker.example");
  expect(screen.queryByText(/Authorization succeeded/)).not.toBeInTheDocument();
  sendResult(popup);
  expect(
    await screen.findByText(/Authorization succeeded with PKCE parameters/)
  ).toBeInTheDocument();
  expect(popup.close).toHaveBeenCalledTimes(1);
});

test("reuses stored edit credentials and invalidates the result after edits", async () => {
  const user = setupUser();
  const fetchSpy = mockEndpoints();
  const { popup } = fakePopup();
  const values = { ...fields, clientId: "********", clientSecret: "" };
  const { rerender } = render(
    <OAuthConnectionCheck values={values} configId={17} />
  );
  await user.click(screen.getByRole("button", { name: "Start Checks" }));
  await waitFor(() => expect(popup.location.href).toContain("test-state"));
  const call = fetchSpy.mock.calls.find(([url]) =>
    String(url).endsWith("test/initiate")
  );
  const body = JSON.parse(String(call?.[1]?.body));
  expect(body.oauth_config_id).toBe(17);
  expect(body).not.toHaveProperty("client_secret");
  expect(body).not.toHaveProperty("client_id");
  sendResult(popup);
  expect(
    await screen.findByText(/Authorization succeeded/)
  ).toBeInTheDocument();
  rerender(
    <OAuthConnectionCheck
      values={{ ...values, supportsPkce: false }}
      configId={17}
    />
  );
  expect(screen.queryByText(/Authorization succeeded/)).not.toBeInTheDocument();
  expect(
    screen.getByText("Settings changed. Test the current settings again.")
  ).toBeInTheDocument();
});

test("reports blocked and closed popups", async () => {
  const user = setupUser();
  mockEndpoints();
  jest.spyOn(window, "open").mockReturnValue(null);
  render(<OAuthConnectionCheck values={fields} />);
  await user.click(screen.getByRole("button", { name: "Start Checks" }));
  expect(
    await screen.findByText("Allow popups and try again.")
  ).toBeInTheDocument();
  const { popup } = fakePopup();
  await user.click(screen.getByRole("button", { name: "Start Checks" }));
  await waitFor(() => expect(popup.location.href).toContain("test-state"));
  popup.closed = true;
  expect(
    await screen.findByText(
      "Test window closed or disconnected. Finish any open test, or try again."
    )
  ).toBeInTheDocument();
});

test("cancels testing when fields change", async () => {
  const user = setupUser();
  mockEndpoints();
  const { popup } = fakePopup();
  const { rerender } = render(<OAuthConnectionCheck values={fields} />);
  await user.click(screen.getByRole("button", { name: "Start Checks" }));
  await waitFor(() => expect(popup.location.href).toContain("https:"));
  rerender(
    <OAuthConnectionCheck values={{ ...fields, authorizationUrl: "" }} />
  );
  expect(popup.close).toHaveBeenCalledTimes(1);
  sendResult(popup);
  expect(screen.queryByText(/Authorization succeeded/)).not.toBeInTheDocument();
});

test("can retry after canceling a pending test and restoring its settings", async () => {
  const user = setupUser();
  const fetchSpy = mockEndpoints();
  const { popup } = fakePopup();
  const { rerender } = render(<OAuthConnectionCheck values={fields} />);
  await user.click(screen.getByRole("button", { name: "Start Checks" }));
  await waitFor(() => expect(popup.location.href).toContain("test-state"));
  rerender(
    <OAuthConnectionCheck values={{ ...fields, supportsPkce: false }} />
  );
  expect(popup.close).toHaveBeenCalledTimes(1);
  rerender(<OAuthConnectionCheck values={fields} />);
  const retry = screen.getByRole("button", { name: "Start Checks" });
  expect(retry).toBeEnabled();
  await user.click(retry);
  await waitFor(() =>
    expect(
      fetchSpy.mock.calls.filter(([url]) =>
        String(url).endsWith("test/initiate")
      )
    ).toHaveLength(2)
  );
});

test("receives a channel result after provider isolation disconnects the popup", async () => {
  const user = setupUser();
  mockEndpoints();
  const { popup } = fakePopup();
  const channel = {
    onmessage: null as ((event: MessageEvent<unknown>) => void) | null,
    close: jest.fn(),
  };
  const originalChannel = Object.getOwnPropertyDescriptor(
    globalThis,
    "BroadcastChannel"
  );
  const construct = jest.fn(() => channel);
  Object.defineProperty(globalThis, "BroadcastChannel", {
    configurable: true,
    value: construct,
  });
  try {
    render(<OAuthConnectionCheck values={fields} />);
    await user.click(screen.getByRole("button", { name: "Start Checks" }));
    await waitFor(() => expect(popup.location.href).toContain("test-state"));
    expect(construct).toHaveBeenCalledWith(oauthTestChannelName("test-state"));
    popup.closed = true;
    expect(
      await screen.findByText(
        "Test window closed or disconnected. Finish any open test, or try again."
      )
    ).toBeInTheDocument();
    expect(channel.close).not.toHaveBeenCalled();
    const message = (state: string) =>
      new MessageEvent("message", {
        data: {
          type: OAUTH_TEST_MESSAGE_TYPE,
          state,
          result: { status: "success", supports_pkce: true },
        },
      });
    act(() => channel.onmessage?.(message("wrong-state")));
    expect(
      screen.queryByText(/Authorization succeeded/)
    ).not.toBeInTheDocument();
    act(() => channel.onmessage?.(message("test-state")));
    expect(
      await screen.findByText(/Authorization succeeded with PKCE parameters/)
    ).toBeInTheDocument();
    expect(channel.close).toHaveBeenCalledTimes(1);
  } finally {
    if (originalChannel)
      Object.defineProperty(globalThis, "BroadcastChannel", originalChannel);
    else Reflect.deleteProperty(globalThis, "BroadcastChannel");
  }
});
