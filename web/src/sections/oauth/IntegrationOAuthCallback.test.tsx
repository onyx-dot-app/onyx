import { render, screen, waitFor } from "@tests/setup/test-utils";
import IntegrationOAuthCallback from "@/sections/oauth/IntegrationOAuthCallback";
import messages from "@/i18n/messages/en.json";
import { mockFetch, requestBody } from "@tests/setup/integrationTestUtils";

const copy = messages.plugins.member.oauthCallback;
const mockReplace = jest.fn();
let mockParams = new URLSearchParams();

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ push: mockReplace, replace: mockReplace }),
  usePathname: () => window.location.pathname,
  useSearchParams: () => mockParams,
}));

const CALLBACK = "/api/integrations/oauth/callback";
const mockLoadPage = jest.fn();
jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  loadPage: (url: string, options?: { replace?: boolean }) =>
    mockLoadPage(url, options),
}));

beforeEach(() => {
  mockReplace.mockClear();
  mockLoadPage.mockClear();
  mockParams = new URLSearchParams({ code: "code-1", state: "attempt-1" });
  window.sessionStorage.clear();
  window.history.replaceState(null, "", "/oauth/callback");
});
afterEach(() => jest.restoreAllMocks());

test("posts the code to the integration API and goes to the return path", async () => {
  const fetchMock = mockFetch({
    [`POST ${CALLBACK}`]: {
      integration_id: 4,
      return_path: "/app/customize/plugins/abc?tab=integrations",
    },
  });
  render(<IntegrationOAuthCallback />);
  await waitFor(() =>
    expect(mockLoadPage).toHaveBeenCalledWith(
      "/app/customize/plugins/abc?tab=integrations",
      { replace: true }
    )
  );
  expect(requestBody(fetchMock, "POST", CALLBACK)).toEqual({
    code: "code-1",
    state: "attempt-1",
  });
  expect(fetchMock).toHaveBeenCalledTimes(1);
});

test("goes to the Plugins page when the return path is not a page of the app", async () => {
  mockFetch({
    [`POST ${CALLBACK}`]: {
      integration_id: 4,
      return_path: "https://example.com/steal",
    },
  });
  render(<IntegrationOAuthCallback />);
  await waitFor(() =>
    expect(mockLoadPage).toHaveBeenCalledWith("/app/customize/integrations", {
      replace: true,
    })
  );
});

test("closes a tab that a waiting page opened instead of navigating", async () => {
  window.sessionStorage.setItem("onyx:oauth-launch", "attempt-1");
  const close = jest.spyOn(window, "close").mockImplementation(() => {});
  mockFetch({
    [`POST ${CALLBACK}`]: { integration_id: 4, return_path: "/app" },
  });
  render(<IntegrationOAuthCallback />);
  await waitFor(() => expect(close).toHaveBeenCalled());
  expect(mockLoadPage).not.toHaveBeenCalled();
});

test("shows the error of a failed exchange", async () => {
  mockFetch({
    [`POST ${CALLBACK}`]: new Response(
      JSON.stringify({ detail: "The sign-in expired." }),
      { status: 400 }
    ),
  });
  render(<IntegrationOAuthCallback />);
  expect(await screen.findByText("The sign-in expired.")).toBeVisible();
  expect(screen.getByText(copy.errorTitle)).toBeVisible();
});

test("a provider error sends no code", async () => {
  mockParams = new URLSearchParams({
    error: "access_denied",
    state: "attempt-1",
  });
  const fetchMock = mockFetch({});
  render(<IntegrationOAuthCallback />);
  expect(await screen.findByText(copy.cancelled)).toBeVisible();
  expect(fetchMock).not.toHaveBeenCalled();
});
