/**
 * @jest-environment jsdom
 */
import { render, screen, waitFor } from "@tests/setup/test-utils";
import Page from "@/app/auth/error/page";

const mockReplace = jest.fn();
let mockError: string | null = null;

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace }),
  usePathname: () => "/auth/error",
  useSearchParams: () => ({ get: () => mockError }),
}));

// The shell fetches workspace settings, which this page's behavior doesn't use.
jest.mock("@/components/auth/AuthFlowContainer", () => ({
  __esModule: true,
  default: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

const STALE_SIGN_IN_MESSAGE =
  "This sign-in link has expired or is no longer valid. Please sign in again.";

beforeEach(() => {
  window.sessionStorage.clear();
});

afterEach(() => {
  jest.restoreAllMocks();
});

describe("auth error page", () => {
  test("restarts sign-in for a stale state without showing the error", async () => {
    mockError = "ACCESS_TOKEN_DECODE_ERROR";

    render(<Page />);

    await waitFor(() =>
      expect(mockReplace).toHaveBeenCalledWith("/auth/login")
    );
    expect(screen.queryByText(STALE_SIGN_IN_MESSAGE)).not.toBeInTheDocument();
  });

  test("shows the error when the restarted sign-in fails the same way", async () => {
    mockError = "ACCESS_TOKEN_ALREADY_EXPIRED";
    const first = render(<Page />);
    await waitFor(() => expect(mockReplace).toHaveBeenCalledTimes(1));
    first.unmount();
    mockReplace.mockReset();

    render(<Page />);

    expect(await screen.findByText(STALE_SIGN_IN_MESSAGE)).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  test("shows the error when storage is blocked and the restart can't be guarded", async () => {
    mockError = "OAUTH_INVALID_STATE";
    jest.spyOn(window, "sessionStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    render(<Page />);

    expect(await screen.findByText(STALE_SIGN_IN_MESSAGE)).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  test("shows any other error without restarting", async () => {
    mockError = "OAUTH_USER_ALREADY_EXISTS";

    render(<Page />);

    expect(
      await screen.findByText(/already exists under a different sign-in method/)
    ).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });
});
