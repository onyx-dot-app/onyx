import { within } from "@testing-library/react";
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import OAuthProviderConnections from "@/sections/oauth-provider/OAuthProviderConnections";

let mockEnabled = true;

jest.mock("@/lib/settings/hooks", () => ({
  useSettings: () => ({ oauth_provider_enabled: mockEnabled }),
}));

jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: {
      id: "owner",
    },
  }),
}));

const grant = {
  id: "00000000-0000-0000-0000-000000000001",
  client_name: "Onyx test client",
  client_id: "client",
  resource: "https://onyx.example/mcp/",
  scopes: ["read:search"],
  created_at: "2026-09-01T00:00:00Z",
  expires_at: "2026-10-01T00:00:00Z",
};

beforeEach(() => {
  mockEnabled = true;
});

afterEach(() => jest.restoreAllMocks());

test("hides the section and makes no request when OAuth provider is unavailable", () => {
  mockEnabled = false;
  const fetchMock = jest.spyOn(global, "fetch");

  const { container } = render(<OAuthProviderConnections />);

  expect(container).toBeEmptyDOMElement();
  expect(fetchMock).not.toHaveBeenCalled();
});

test("disconnects only after confirmation and updates the list", async () => {
  let deleted = false;
  const fetchMock = jest
    .spyOn(global, "fetch")
    .mockImplementation(async (_url, options) => {
      if (options?.method === "DELETE") {
        deleted = true;
        return new Response(JSON.stringify({ revoked: true }));
      }
      return new Response(JSON.stringify(deleted ? [] : [grant]));
    });
  const user = setupUser();

  render(<OAuthProviderConnections />);

  await screen.findByText("Onyx test client");
  await user.click(
    screen.getByRole("button", { name: "Disconnect Onyx test client" })
  );
  expect(deleted).toBe(false);
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: "Disconnect" }));
  await screen.findByText("No connected apps.");
  expect(fetchMock).toHaveBeenCalledWith(
    `/api/oauth-provider/grants/${grant.id}`,
    { method: "DELETE" }
  );
  await waitFor(() =>
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument()
  );
});
