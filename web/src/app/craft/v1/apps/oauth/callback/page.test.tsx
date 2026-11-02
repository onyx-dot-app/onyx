import { render, waitFor } from "@tests/setup/test-utils";
import ExternalAppsOAuthCallbackPage from "@/app/craft/v1/apps/oauth/callback/page";
import { completeExternalAppOAuthCallback } from "@/app/craft/services/externalAppsService";
import { OAUTH_POPUP_MESSAGE_SOURCE } from "@/app/craft/types/setupRequests";

const replace = jest.fn();
const push = jest.fn();
const params = new URLSearchParams({ code: "code", state: "state" });

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push }),
  useSearchParams: () => params,
}));
jest.mock("@/app/craft/services/externalAppsService", () => ({
  completeExternalAppOAuthCallback: jest.fn(),
}));

beforeEach(() => {
  jest.clearAllMocks();
  Object.defineProperty(window, "opener", {
    configurable: true,
    value: { postMessage: jest.fn() },
  });
  jest.spyOn(window, "close").mockImplementation(() => {});
});
afterEach(() => jest.restoreAllMocks());

test("member OAuth routes to verified completion before sending any popup result", async () => {
  jest.mocked(completeExternalAppOAuthCallback).mockResolvedValue({
    success: true,
    external_app_id: 7,
    return_path:
      "/app/plugins/oauth/complete?pluginKind=external-app&pluginId=7&attempt=nonce",
  });
  render(<ExternalAppsOAuthCallbackPage />);
  await waitFor(() =>
    expect(replace).toHaveBeenCalledWith(
      "/app/plugins/oauth/complete?pluginKind=external-app&pluginId=7&attempt=nonce&message=oauth_connected"
    )
  );
  expect(window.opener.postMessage).not.toHaveBeenCalled();
  expect(window.close).not.toHaveBeenCalled();
});

test("legacy SetupCard OAuth retains its original popup message and close", async () => {
  jest
    .mocked(completeExternalAppOAuthCallback)
    .mockResolvedValue({ success: true, external_app_id: 7 });
  render(<ExternalAppsOAuthCallbackPage />);
  await waitFor(() =>
    expect(window.opener.postMessage).toHaveBeenCalledWith(
      { source: OAUTH_POPUP_MESSAGE_SOURCE, externalAppId: 7 },
      window.location.origin
    )
  );
  expect(window.close).toHaveBeenCalledTimes(1);
  expect(replace).not.toHaveBeenCalled();
});

test("rejects an external return URL without signalling success", async () => {
  jest.mocked(completeExternalAppOAuthCallback).mockResolvedValue({
    success: true,
    external_app_id: 7,
    return_path: "https://example.com/app/plugins/oauth/complete",
  });
  render(<ExternalAppsOAuthCallbackPage />);
  await waitFor(() =>
    expect(completeExternalAppOAuthCallback).toHaveBeenCalled()
  );
  expect(replace).not.toHaveBeenCalled();
  expect(window.opener.postMessage).not.toHaveBeenCalled();
});
