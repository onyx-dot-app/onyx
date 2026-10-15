/** @jest-environment jsdom */
import { render, screen } from "@tests/setup/test-utils";
import OAuthConfigCallbackPage from "@/app/oauth-config/callback/page";
import { OAUTH_TEST_ACTIVE_KEY } from "@/lib/oauth/testConnection";

jest.mock("@/components/oauth/OAuthCallbackPage", () => ({
  __esModule: true,
  default: () => <div data-testid="normal-callback" />,
}));
jest.mock("@/sections/actions/oauth/OAuthTestCallback", () => ({
  __esModule: true,
  default: () => <div data-testid="test-callback" />,
}));

afterEach(() => {
  window.sessionStorage.clear();
  window.history.replaceState({}, "", "/");
});

it.each([
  ["stale-test", "normal-callback"],
  ["current-state", "test-callback"],
])("selects the callback for active marker %s", async (marker, expected) => {
  window.history.replaceState(
    {},
    "",
    "/oauth-config/callback?state=current-state"
  );
  window.sessionStorage.setItem(OAUTH_TEST_ACTIVE_KEY, marker);
  render(<OAuthConfigCallbackPage />);
  expect(await screen.findByTestId(expected)).toBeInTheDocument();
});
