/**
 * @jest-environment jsdom
 */
import { render, screen } from "@tests/setup/test-utils";
import LoginPage from "@/app/auth/login/LoginPage";
import type { AuthTypeMetadata } from "@/lib/auth/types";

function metadata(overrides: Partial<AuthTypeMetadata>): AuthTypeMetadata {
  return {
    multiTenant: false,
    requiresVerification: false,
    anonymousUserEnabled: false,
    passwordMinLength: 8,
    passwordMaxLength: 64,
    passwordRequireUppercase: false,
    passwordRequireLowercase: false,
    passwordRequireDigit: false,
    passwordRequireSpecialChar: false,
    hasUsers: true,
    oauthEnabled: false,
    passwordAuthEnabled: true,
    magicLinkEnabled: false,
    ssoProviders: [],
    ...overrides,
  };
}

function renderLogin(authTypeMetadata: AuthTypeMetadata) {
  render(
    <LoginPage
      authUrl={null}
      authTypeMetadata={authTypeMetadata}
      nextUrl={null}
      hidePageRedirect
      autoRedirectToSso={false}
    />
  );
}

const LINK_BUTTON = { name: "Get a link by email" };

describe("LoginPage with the magic link", () => {
  test("on multi-tenant the link takes the password form's place", () => {
    renderLogin(metadata({ multiTenant: true, magicLinkEnabled: true }));

    expect(screen.getByRole("button", LINK_BUTTON)).toBeInTheDocument();
    expect(screen.queryByTestId("password")).not.toBeInTheDocument();
  });

  test("on multi-tenant without it the password form stays", () => {
    renderLogin(metadata({ multiTenant: true }));

    expect(screen.queryByRole("button", LINK_BUTTON)).not.toBeInTheDocument();
    expect(screen.getByTestId("password")).toBeInTheDocument();
  });

  test("on self-hosted the link sits next to the password form", () => {
    renderLogin(metadata({ magicLinkEnabled: true }));

    expect(screen.getByRole("button", LINK_BUTTON)).toBeInTheDocument();
    expect(screen.getByTestId("password")).toBeInTheDocument();
  });
});
