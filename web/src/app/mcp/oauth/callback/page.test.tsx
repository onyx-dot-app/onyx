import { render, screen, waitFor } from "@tests/setup/test-utils";
import MCPOAuthCallbackPage from "@/app/mcp/oauth/callback/page";
import { completeMCPUserOAuth } from "@/lib/mcp/svc";
import messages from "@/i18n/messages/en.json";

let mockSearchParams = new URLSearchParams();
const mockPush = jest.fn();
const mockRouter = { push: mockPush };
jest.mock("next/navigation", () => ({
  useSearchParams: () => mockSearchParams,
  useRouter: () => mockRouter,
}));
jest.mock("@/lib/mcp/svc", () => ({ completeMCPUserOAuth: jest.fn() }));

beforeEach(() => {
  jest.clearAllMocks();
  jest
    .mocked(completeMCPUserOAuth)
    .mockRejectedValue(new Error("Authorization cancelled"));
  jest.spyOn(console, "error").mockImplementation(() => undefined);
});
afterEach(() => jest.restoreAllMocks());

test("provider denial consumes the staged attempt and keeps the cancelled screen", async () => {
  mockSearchParams = new URLSearchParams({
    state: "mcp-setup_attempt",
    error: "access_denied",
  });
  render(<MCPOAuthCallbackPage />);
  await waitFor(() =>
    expect(completeMCPUserOAuth).toHaveBeenCalledWith(
      null,
      "mcp-setup_attempt",
      "access_denied"
    )
  );
  expect(
    screen.getByText(messages.actions.mcpOauthCallback.cancelled.title)
  ).toBeVisible();
  expect(mockPush).not.toHaveBeenCalled();
});

test("denial without a state does not send an uncorrelated cancellation", async () => {
  mockSearchParams = new URLSearchParams({ error: "access_denied" });
  render(<MCPOAuthCallbackPage />);
  expect(
    await screen.findByText(messages.actions.mcpOauthCallback.cancelled.title)
  ).toBeVisible();
  expect(completeMCPUserOAuth).not.toHaveBeenCalled();
});
