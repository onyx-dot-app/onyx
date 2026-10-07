/**
 * @jest-environment jsdom
 */
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import ProviderSignInButton from "@/app/auth/login/ProviderSignInButton";
import type { SSOProviderOption } from "@/lib/auth/types";

const OKTA: SSOProviderOption = {
  name: "okta",
  displayName: "Okta",
  providerType: "OIDC",
  authorizeUrl: "/api/auth/oidc/okta/authorize",
};

// jsdom only implements hash navigation and its Location cannot be replaced,
// so the "IdP" the button navigates to is a hash on the test origin.
const IDP_URL = "http://localhost/#idp-authorize?state=signed";
const AUTHORIZE_URL = "http://localhost/api/auth/oidc/okta/authorize";

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

beforeEach(() => {
  window.history.replaceState(null, "", "/");
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("ProviderSignInButton", () => {
  test("waits for a click by default", async () => {
    // Mock GET /api/auth/oidc/okta/authorize
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(200, { authorization_url: IDP_URL }));
    const user = setupUser();

    render(<ProviderSignInButton provider={OKTA} nextUrl="/app?q=1" />);

    expect(fetchMock).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "Okta" }));

    await waitFor(() => expect(window.location.href).toBe(IDP_URL));
    expect(fetchMock).toHaveBeenCalledWith(
      `${AUTHORIZE_URL}?next=%2Fapp%3Fq%3D1`,
      { credentials: "include" }
    );
  });

  test("starts the flow on mount with autoStart, carrying next", async () => {
    // Mock GET /api/auth/oidc/okta/authorize
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(200, { authorization_url: IDP_URL }));

    render(
      <ProviderSignInButton
        provider={OKTA}
        nextUrl="/app?user-prompt=hello"
        autoStart
      />
    );

    await waitFor(() => expect(window.location.href).toBe(IDP_URL));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock).toHaveBeenCalledWith(
      `${AUTHORIZE_URL}?next=%2Fapp%3Fuser-prompt%3Dhello`,
      { credentials: "include" }
    );
    expect(screen.getByText("Taking you to Okta to sign in…")).toBeVisible();
    expect(screen.getByRole("button", { name: "Okta" })).toBeDisabled();
  });

  test("starts once even when the effect runs twice", async () => {
    // Mock GET /api/auth/oidc/okta/authorize
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(200, { authorization_url: IDP_URL }));

    const { rerender } = render(
      <ProviderSignInButton provider={OKTA} nextUrl={null} autoStart />
    );
    rerender(<ProviderSignInButton provider={OKTA} nextUrl={null} autoStart />);

    await waitFor(() => expect(window.location.href).toBe(IDP_URL));
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("falls back to the button when the auto-start fails", async () => {
    // Mock GET /api/auth/oidc/okta/authorize (IdP unreachable)
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(502, { detail: "idp unreachable" }));

    render(<ProviderSignInButton provider={OKTA} nextUrl={null} autoStart />);

    expect(
      await screen.findByText("Could not start sign-in (status 502)")
    ).toBeVisible();
    expect(screen.getByRole("button", { name: "Okta" })).toBeEnabled();
    expect(window.location.href).toBe("http://localhost/");
  });
});
