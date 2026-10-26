import { StrictMode } from "react";
import { render, screen, waitFor } from "@tests/setup/test-utils";
import OAuthConfigCallbackPage from "@/app/oauth-config/callback/page";
jest.mock("@/components/oauth/OAuthCallbackPage", () => ({
  __esModule: true,
  default: () => <div>Normal callback</div>,
}));
import {
  OAUTH_TEST_ACTIVE_KEY,
  oauthTestStorageKey,
} from "@/lib/oauth/testConnection";
const query = new URLSearchParams();
jest.mock("next/navigation", () => ({ useSearchParams: () => query }));
beforeEach(() => {
  window.history.replaceState(null, "", "/oauth-config/callback");
  window.sessionStorage.clear();
  query.delete("code");
  query.delete("state");
  query.delete("error");
  query.set("code", "authorization-code");
  query.set("state", "test-state");
});
afterEach(() => jest.restoreAllMocks());
function preparePopup() {
  sessionStorage.setItem(OAUTH_TEST_ACTIVE_KEY, "test-state");
  sessionStorage.setItem(oauthTestStorageKey("test-state"), "pending");
  const postMessage = jest.fn();
  Object.defineProperty(window, "opener", {
    configurable: true,
    value: { postMessage },
  });
  return postMessage;
}
test("completes once in StrictMode without running the normal callback", async () => {
  const postMessage = preparePopup();
  // POST test/callback returns a diagnostic result, not a persisted token.
  const fetchSpy = jest
    .spyOn(global, "fetch")
    .mockResolvedValue(new Response(JSON.stringify({ supports_pkce: true })));
  render(
    <StrictMode>
      <OAuthConfigCallbackPage />
    </StrictMode>
  );
  expect(
    await screen.findByText(/Authorization succeeded with PKCE parameters/)
  ).toBeInTheDocument();
  expect(fetchSpy).toHaveBeenCalledTimes(1);
  expect(fetchSpy.mock.calls[0]?.[0]).toBe(
    "/api/admin/oauth-config/test/callback?code=authorization-code&state=test-state"
  );
  expect(screen.queryByText("Normal callback")).not.toBeInTheDocument();
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      state: "test-state",
      result: { status: "success", supports_pkce: true },
    }),
    window.location.origin
  );
  expect(sessionStorage.getItem(OAUTH_TEST_ACTIVE_KEY)).toBeNull();
  expect(sessionStorage.getItem(oauthTestStorageKey("test-state"))).toBeNull();
  expect(window.location.search).toBe("?oauth_test_completed=1");
});
test("reports provider denial without exchanging a code", async () => {
  const postMessage = preparePopup();
  query.set("error", "access_denied");
  const fetchSpy = jest.spyOn(global, "fetch");
  render(<OAuthConfigCallbackPage />);
  expect(
    await screen.findByText("Provider authorization was declined or canceled.")
  ).toBeInTheDocument();
  expect(fetchSpy).not.toHaveBeenCalled();
  expect(postMessage).toHaveBeenCalledWith(
    expect.objectContaining({ result: { status: "denied" } }),
    window.location.origin
  );
});
test("does not redeem again after a reload interrupts an exchange", async () => {
  preparePopup();
  sessionStorage.setItem(oauthTestStorageKey("test-state"), "exchanging");
  const fetchSpy = jest.spyOn(global, "fetch");
  render(<OAuthConfigCallbackPage />);
  expect(
    await screen.findByText(
      "The test expired or was interrupted. Start a new test."
    )
  ).toBeInTheDocument();
  expect(fetchSpy).not.toHaveBeenCalled();
});
test("ordinary callbacks keep their original component", async () => {
  render(<OAuthConfigCallbackPage />);
  await waitFor(() =>
    expect(screen.getByText("Normal callback")).toBeInTheDocument()
  );
});
