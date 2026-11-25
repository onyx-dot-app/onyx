/**
 * @jest-environment jsdom
 */
import { render, screen, setupUser, waitFor } from "@tests/setup/test-utils";
import MagicLinkRedeem from "@/app/auth/magic-link/MagicLinkRedeem";

const mockGo = jest.fn();
const mockLoad = jest.fn();
let mockToken: string | null = "tok";

jest.mock("@opal/navigation", () => ({
  ...jest.requireActual<typeof import("@opal/navigation")>("@opal/navigation"),
  useNavigation: () => ({
    go: mockGo,
    load: mockLoad,
    linkTo: (href: string) => ({ href, onClick: jest.fn() }),
  }),
  useSearchParams: () =>
    new URLSearchParams(mockToken === null ? {} : { token: mockToken }),
}));

// The shell fetches workspace settings, which this page's behavior doesn't use.
jest.mock("@/components/auth/AuthFlowContainer", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

function jsonResponse(status: number, body: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

function signedIn(nextUrl: string): Response {
  return jsonResponse(200, {
    state: "signed_in",
    next_url: nextUrl,
    team_choice_token: null,
  });
}

const TEAM_CHOICE = jsonResponse(200, {
  state: "team_choice",
  next_url: null,
  team_choice_token: "tok2",
});

function redeemedTokens(fetchMock: jest.SpyInstance): string[] {
  return fetchMock.mock.calls.map(
    ([, init]) => JSON.parse(String(init.body)).token
  );
}

beforeEach(() => {
  mockToken = "tok";
  mockGo.mockReset();
  mockLoad.mockReset();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("MagicLinkRedeem", () => {
  test("redeems the token once and loads the next page", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValue(signedIn("/app/chat?id=42"));

    // The effect runs again on a re-render (a new navigation object here,
    // or dev StrictMode in the browser); the token must still go once.
    const { rerender } = render(<MagicLinkRedeem />);
    rerender(<MagicLinkRedeem />);

    await waitFor(() =>
      expect(mockLoad).toHaveBeenCalledWith("/app/chat?id=42", {
        replace: true,
      })
    );
    expect(redeemedTokens(fetchMock)).toEqual(["tok"]);
    expect(fetchMock.mock.calls[0]?.[0]).toBe("/api/auth/magic-link/redeem");
  });

  test("an off-site next page falls back to the app", async () => {
    jest.spyOn(global, "fetch").mockResolvedValue(signedIn("//evil.example"));

    render(<MagicLinkRedeem />);

    await waitFor(() =>
      expect(mockLoad).toHaveBeenCalledWith("/app", { replace: true })
    );
  });

  test("a link without a token is an invalid link", async () => {
    mockToken = null;
    const fetchMock = jest.spyOn(global, "fetch");

    render(<MagicLinkRedeem />);

    await waitFor(() =>
      expect(mockGo).toHaveBeenCalledWith(
        "/auth/error?error=MAGIC_LINK_INVALID",
        { replace: true }
      )
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  test.each([
    "MAGIC_LINK_INVALID",
    "MAGIC_LINK_USE_SSO",
    "PLAYGROUND_EMAIL_USED",
  ])("a %s refusal opens the error page with its code", async (code) => {
    jest
      .spyOn(global, "fetch")
      .mockResolvedValue(jsonResponse(403, { detail: code }));

    render(<MagicLinkRedeem />);

    await waitFor(() =>
      expect(mockGo).toHaveBeenCalledWith(`/auth/error?error=${code}`, {
        replace: true,
      })
    );
    expect(mockLoad).not.toHaveBeenCalled();
  });

  test("a network failure opens the error page's general message", async () => {
    jest.spyOn(global, "fetch").mockRejectedValue(new TypeError("offline"));

    render(<MagicLinkRedeem />);

    await waitFor(() =>
      expect(mockGo).toHaveBeenCalledWith("/auth/error", { replace: true })
    );
  });

  test("a running trial asks join or new, and new redeems the fresh token", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(TEAM_CHOICE)
      .mockResolvedValueOnce(signedIn("/app"));
    const user = setupUser();

    render(<MagicLinkRedeem />);
    await user.click(
      await screen.findByRole("button", { name: "Start a new team" })
    );

    await waitFor(() =>
      expect(mockLoad).toHaveBeenCalledWith("/app", { replace: true })
    );
    expect(redeemedTokens(fetchMock)).toEqual(["tok", "tok2"]);
  });

  test("joining a team asks for an invite and redeems nothing more", async () => {
    const fetchMock = jest
      .spyOn(global, "fetch")
      .mockResolvedValueOnce(TEAM_CHOICE);
    const user = setupUser();

    render(<MagicLinkRedeem />);
    await user.click(
      await screen.findByRole("button", { name: "Join your team" })
    );

    expect(
      screen.getByText("Ask your admin to invite you.")
    ).toBeInTheDocument();
    expect(redeemedTokens(fetchMock)).toEqual(["tok"]);
    expect(mockLoad).not.toHaveBeenCalled();
  });
});
