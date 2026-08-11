// Guards the /api/me contract: unresolved reads as loading and failed auth fetches self-heal.
import { act, render, screen } from "@tests/setup/test-utils";
// Relative import: jest's moduleNameMapper swaps the @/ path for the global stub.
import { UserProvider, useUser } from "./UserProvider";
import { FetchError } from "@/lib/fetcher";
import { useCurrentUser } from "@/lib/users/hooks";
import { User } from "@/lib/types";

jest.mock("posthog-js/react", () => ({ usePostHog: () => undefined }));
jest.mock("@/lib/settings/hooks", () => ({ useSettings: () => ({}) }));
jest.mock("@/lib/users/hooks", () => ({ useCurrentUser: jest.fn() }));
jest.mock("@/lib/auth/hooks", () => ({
  useAuthTypeMetadata: () => ({
    authTypeMetadata: undefined,
    isLoading: false,
  }),
  useTokenRefresh: jest.fn(),
}));
jest.mock("@/lib/users/svc", () => ({
  updateUserPersonalization: jest.fn(),
  setUserDefaultModel: jest.fn(),
}));
jest.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: jest.fn() }),
}));

const mockedUseCurrentUser = jest.mocked(useCurrentUser);

function setCurrentUser(overrides: Partial<ReturnType<typeof useCurrentUser>>) {
  mockedUseCurrentUser.mockReturnValue({
    user: undefined,
    isLoading: true,
    mutateUser: jest.fn(),
    userError: undefined,
    ...overrides,
  } as ReturnType<typeof useCurrentUser>);
}

function Probe() {
  const { user, userResolution } = useUser();
  if (userResolution !== "resolved") {
    return <span>{userResolution}</span>;
  }
  return <span>{user ? user.email : "signed-out"}</span>;
}

// Factory: an identical element reference would let React skip the re-render.
function probeTree() {
  return (
    <UserProvider>
      <Probe />
    </UserProvider>
  );
}

function renderProbe() {
  return render(probeTree());
}

describe("UserProvider user resolution", () => {
  it("reports loading while /api/me is unresolved", () => {
    setCurrentUser({ user: undefined });
    renderProbe();
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("reports loading when /api/me failed instead of signed-out", () => {
    setCurrentUser({
      user: undefined,
      isLoading: false,
      userError: new Error("transient"),
    });
    renderProbe();
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("reports signed-out only for a resolved null user", () => {
    setCurrentUser({ user: null, isLoading: false });
    renderProbe();
    expect(screen.getByText("signed-out")).toBeInTheDocument();
  });

  it("exposes the user once resolved", () => {
    setCurrentUser({
      user: { id: "u1", email: "john@example.com" } as User,
      isLoading: false,
    });
    renderProbe();
    expect(screen.getByText("john@example.com")).toBeInTheDocument();
  });
});

function authError(label: string): FetchError {
  return new FetchError(label, 403, null);
}

describe("UserProvider /api/me retry", () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("retries an auth failure on a backoff schedule, then reports unavailable", () => {
    const mutateUser = jest.fn();

    setCurrentUser({ userError: authError("fail 1"), mutateUser });
    const { rerender } = renderProbe();
    act(() => jest.advanceTimersByTime(2_000));
    expect(mutateUser).toHaveBeenCalledTimes(1);

    setCurrentUser({ userError: authError("fail 2"), mutateUser });
    rerender(probeTree());
    act(() => jest.advanceTimersByTime(5_000));
    expect(mutateUser).toHaveBeenCalledTimes(2);

    setCurrentUser({ userError: authError("fail 3"), mutateUser });
    rerender(probeTree());
    act(() => jest.advanceTimersByTime(15_000));
    expect(mutateUser).toHaveBeenCalledTimes(3);

    setCurrentUser({ userError: authError("fail 4"), mutateUser });
    rerender(probeTree());
    act(() => jest.advanceTimersByTime(120_000));
    expect(mutateUser).toHaveBeenCalledTimes(3);
    // Budget spent: unavailable, never a false signed-out claim.
    expect(screen.getByText("unavailable")).toBeInTheDocument();
  });

  it("does not schedule retries for non-auth failures (SWR owns those)", () => {
    const mutateUser = jest.fn();

    setCurrentUser({
      userError: new FetchError("boom", 500, null),
      mutateUser,
    });
    renderProbe();
    act(() => jest.advanceTimersByTime(29_000));
    expect(mutateUser).not.toHaveBeenCalled();
    expect(screen.getByText("loading")).toBeInTheDocument();
  });

  it("reports unavailable once a non-auth failure outlives the deadline", () => {
    setCurrentUser({ userError: new FetchError("boom", 500, null) });
    renderProbe();
    act(() => jest.advanceTimersByTime(31_000));
    expect(screen.getByText("unavailable")).toBeInTheDocument();
  });

  it("resets the retry budget after a successful fetch", () => {
    const mutateUser = jest.fn();

    setCurrentUser({ userError: authError("fail"), mutateUser });
    const { rerender } = renderProbe();
    act(() => jest.advanceTimersByTime(2_000));
    expect(mutateUser).toHaveBeenCalledTimes(1);

    setCurrentUser({
      user: { id: "u1", email: "john@example.com" } as User,
      isLoading: false,
      mutateUser,
    });
    rerender(probeTree());

    setCurrentUser({ userError: authError("fail again"), mutateUser });
    rerender(probeTree());
    act(() => jest.advanceTimersByTime(2_000));
    expect(mutateUser).toHaveBeenCalledTimes(2);
  });
});
