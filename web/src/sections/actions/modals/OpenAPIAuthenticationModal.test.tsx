import {
  act,
  deferred,
  fireEvent,
  render,
  screen,
  setupUser,
  waitFor,
} from "@tests/setup/test-utils";
import OpenAPIAuthenticationModal from "@/sections/actions/modals/OpenAPIAuthenticationModal";

beforeEach(() => {
  jest.spyOn(global, "fetch").mockImplementation(async (input) => {
    if (String(input) === "/api/auth/type")
      return new Response(JSON.stringify({ oauth_enabled: true }));
    return new Response("{}");
  });
});

test("a save accepted before unmount completes without closing a later form", async () => {
  const user = setupUser();
  const pending = deferred<void>();
  const onConnect = jest.fn(() => pending.promise);
  const onClose = jest.fn();
  const { unmount } = render(
    <OpenAPIAuthenticationModal
      isOpen
      title="Authentication"
      allowNoAuthentication
      defaultMethod="none"
      onBack={jest.fn()}
      onConnect={onConnect}
      onClose={onClose}
    />
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled()
  );
  await user.click(screen.getByRole("button", { name: "Connect" }));
  expect(onConnect).toHaveBeenCalledWith({
    authMethod: "none",
    authorizationUrl: "",
    tokenUrl: "",
    clientId: "",
    clientSecret: "",
    scopes: "",
    supportsPkce: false,
    headers: [{ key: "Authorization", value: "" }],
  });
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDisabled();
  unmount();
  await act(async () => pending.resolve());
  expect(onClose).not.toHaveBeenCalled();
});
afterEach(() => jest.restoreAllMocks());

describe("method-specific validation", () => {
  test.each([
    "No authentication",
    "Custom Authorization Header",
    "OAuth Pass-through",
  ])(
    "hidden invalid OAuth URLs do not block %s and remain in the draft",
    async (method) => {
      const user = setupUser();
      const onConnect = jest.fn();
      const onClose = jest.fn();
      render(
        <OpenAPIAuthenticationModal
          isOpen
          title="Authentication"
          allowNoAuthentication
          onConnect={onConnect}
          onClose={onClose}
        />
      );
      const authorizationUrl = await screen.findByRole("textbox", {
        name: "Authorization URL",
      });
      fireEvent.change(authorizationUrl, { target: { value: "invalid-url" } });
      fireEvent.change(screen.getByRole("textbox", { name: "Token URL" }), {
        target: { value: "invalid-token-url" },
      });
      await user.click(screen.getByRole("combobox"));
      await user.keyboard(
        "{ArrowDown}".repeat(
          method === "No authentication"
            ? 1
            : method === "Custom Authorization Header"
              ? 4
              : 3
        ) + "{Enter}"
      );
      if (method === "Custom Authorization Header") {
        fireEvent.change(screen.getByRole("textbox", { name: "Value 1" }), {
          target: { value: "api-key" },
        });
      }
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Connect" })).toBeEnabled()
      );
      await user.click(screen.getByRole("button", { name: "Connect" }));
      await waitFor(() =>
        expect(onConnect).toHaveBeenCalledWith(
          expect.objectContaining({
            authMethod:
              method === "No authentication"
                ? "none"
                : method === "Custom Authorization Header"
                  ? "custom-header"
                  : "pt-oauth",
            authorizationUrl: "invalid-url",
            tokenUrl: "invalid-token-url",
          })
        )
      );
      await user.click(screen.getByRole("combobox"));
      await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
      expect(
        await screen.findByRole("textbox", { name: "Authorization URL" })
      ).toHaveValue("invalid-url");
      expect(screen.getByRole("textbox", { name: "Token URL" })).toHaveValue(
        "invalid-token-url"
      );
      expect(screen.getByRole("button", { name: "Connect" })).toBeDisabled();
    }
  );
});

describe("inline authentication", () => {
  test("saves through the parent footer without opening or closing a dialog", async () => {
    const user = setupUser();
    const pending = deferred<void>();
    const onConnect = jest.fn(() => pending.promise);
    const onClose = jest.fn();
    const onBusyChange = jest.fn();
    const footerTarget = document.createElement("div");
    document.body.appendChild(footerTarget);
    const { unmount } = render(
      <OpenAPIAuthenticationModal
        presentation="inline"
        footerTarget={footerTarget}
        onBusyChange={onBusyChange}
        isOpen
        title="Authentication"
        submitLabel="Save changes"
        draftValues={{
          authMethod: "oauth",
          authorizationUrl: "https://example.com/authorize",
          tokenUrl: "https://example.com/token",
          clientId: "client",
          clientSecret: "secret",
          scopes: "read",
          supportsPkce: false,
          headers: [],
        }}
        onConnect={onConnect}
        onClose={onClose}
      />
    );
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Cancel" })
    ).not.toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Save changes" });
    expect(footerTarget).toContainElement(save);
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox", { name: /Scopes/ }), {
      target: { value: "read, write" },
    });
    await waitFor(() => expect(save).toBeEnabled());
    await user.click(save);
    expect(onConnect).toHaveBeenCalledTimes(1);
    expect(onConnect).toHaveBeenCalledWith(
      expect.objectContaining({ scopes: "read, write" })
    );
    expect(onBusyChange).toHaveBeenLastCalledWith(true);
    const scopes = screen.getByRole("textbox", { name: /Scopes/ });
    expect(scopes).toBeDisabled();
    expect(screen.getByRole("combobox")).toBeDisabled();
    await user.type(scopes, ", admin");
    expect(scopes).toHaveValue("read, write");
    await act(async () => pending.resolve());
    await waitFor(() => expect(onBusyChange).toHaveBeenLastCalledWith(false));
    expect(scopes).toBeEnabled();
    expect(onClose).not.toHaveBeenCalled();
    unmount();
    footerTarget.remove();
  });

  test("inactive tabs do not render actions in the parent footer", () => {
    const footerTarget = document.createElement("div");
    const { unmount } = render(
      <OpenAPIAuthenticationModal
        presentation="inline"
        footerTarget={footerTarget}
        active={false}
        isOpen
        title="Authentication"
        onClose={jest.fn()}
      />
    );
    expect(footerTarget).toBeEmptyDOMElement();
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    unmount();
  });
});
