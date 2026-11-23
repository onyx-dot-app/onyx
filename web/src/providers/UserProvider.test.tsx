// Guards the /api/me contract: unresolved reads as loading and failed auth fetches self-heal.
import { act, render, screen, waitFor } from "@tests/setup/test-utils";
// Relative import: jest's moduleNameMapper swaps the @/ path for the global stub.
import { UserProvider, useUser } from "./UserProvider";
import { FetchError } from "@/lib/fetcher";
import { useCurrentUser } from "@/lib/users/hooks";
import { User } from "@/lib/types";

jest.mock("posthog-js/react", () => ({ usePostHog: () => undefined }));
jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  useRouter: () => ({ refresh: jest.fn() }),
}));
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
}));
jest.mock("next-themes", () => ({
  useTheme: () => ({ theme: "light", setTheme: jest.fn() }),
}));
const mockToastError = jest.fn();
jest.mock("@opal/layouts", () => ({
  ...jest.requireActual("@opal/layouts"),
  toast: { error: (...args: unknown[]) => mockToastError(...args) },
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

interface Deferred<T> {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason: unknown) => void;
}

function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  let reject: (reason: unknown) => void = () => undefined;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function meResponse(preferences: Partial<User["preferences"]>): Response {
  return new Response(
    JSON.stringify({ id: "u1", email: "john@example.com", preferences }),
    { status: 200, headers: { "Content-Type": "application/json" } }
  );
}

function PreferencesProbe() {
  const { user, refreshUser, updatePreferences } = useUser();
  return (
    <>
      <span>
        {user
          ? `auto-scroll ${user.preferences.auto_scroll}, shortcuts ${user.preferences.shortcut_enabled}`
          : "none"}
      </span>
      <button
        onClick={() =>
          void updatePreferences({ auto_scroll: true }, "/api/auto-scroll")
        }
      >
        enable auto-scroll
      </button>
      <button
        onClick={() =>
          void updatePreferences(
            { shortcut_enabled: true },
            "/api/shortcut-enabled?shortcut_enabled=true"
          )
        }
      >
        enable shortcuts
      </button>
      <button onClick={() => void refreshUser()}>refresh</button>
    </>
  );
}

describe("UserProvider updatePreferences", () => {
  // What GET /api/me returns once the queued responses run out.
  let serverPreferences: Partial<User["preferences"]>;
  let meResponses: Array<Promise<Response>>;
  let patchResponses: Map<string, Deferred<Response>>;

  function patchResponse(endpoint: string): Deferred<Response> {
    const response = patchResponses.get(endpoint) ?? deferred<Response>();
    patchResponses.set(endpoint, response);
    return response;
  }

  function click(name: string) {
    act(() => screen.getByRole("button", { name }).click());
  }

  beforeEach(() => {
    mockToastError.mockClear();
    // Failed saves log the error.
    jest.spyOn(console, "error").mockImplementation(() => undefined);
    mockedUseCurrentUser.mockImplementation(
      jest.requireActual<typeof import("@/lib/users/hooks")>(
        "@/lib/users/hooks"
      ).useCurrentUser
    );
    serverPreferences = { auto_scroll: false, shortcut_enabled: false };
    meResponses = [];
    patchResponses = new Map();
    jest.spyOn(global, "fetch").mockImplementation((input, init) => {
      if (init?.method === "PATCH") return patchResponse(String(input)).promise;
      return (
        meResponses.shift() ?? Promise.resolve(meResponse(serverPreferences))
      );
    });
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  async function renderLoaded() {
    render(
      <UserProvider>
        <PreferencesProbe />
      </UserProvider>
    );
    await screen.findByText("auto-scroll false, shortcuts false");
  }

  it("shows the change at once and keeps it after the save", async () => {
    await renderLoaded();

    click("enable auto-scroll");
    expect(
      screen.getByText("auto-scroll true, shortcuts false")
    ).toBeInTheDocument();

    await act(async () =>
      patchResponse("/api/auto-scroll").resolve(new Response(null))
    );
    expect(
      screen.getByText("auto-scroll true, shortcuts false")
    ).toBeInTheDocument();
    expect(global.fetch).toHaveBeenCalledWith(
      "/api/auto-scroll",
      expect.objectContaining({
        method: "PATCH",
        body: JSON.stringify({ auto_scroll: true }),
      })
    );
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("keeps both of two overlapping saves", async () => {
    await renderLoaded();

    click("enable shortcuts");
    click("enable auto-scroll");
    expect(
      screen.getByText("auto-scroll true, shortcuts true")
    ).toBeInTheDocument();

    await act(async () =>
      patchResponse("/api/shortcut-enabled?shortcut_enabled=true").resolve(
        new Response(null)
      )
    );
    await act(async () =>
      patchResponse("/api/auto-scroll").resolve(new Response(null))
    );

    expect(
      screen.getByText("auto-scroll true, shortcuts true")
    ).toBeInTheDocument();
    expect(mockToastError).not.toHaveBeenCalled();
  });

  it("shows the server state and the error toast when the server rejects a save", async () => {
    await renderLoaded();

    click("enable shortcuts");
    click("enable auto-scroll");
    // The first save lands; the second fails.
    serverPreferences = { auto_scroll: false, shortcut_enabled: true };
    await act(async () =>
      patchResponse("/api/shortcut-enabled?shortcut_enabled=true").resolve(
        new Response(null)
      )
    );
    await act(async () =>
      patchResponse("/api/auto-scroll").resolve(
        new Response(null, { status: 500 })
      )
    );

    expect(
      await screen.findByText("auto-scroll false, shortcuts true")
    ).toBeInTheDocument();
    expect(mockToastError).toHaveBeenCalledWith("Failed to save preferences");
  });

  it("shows the server state and the error toast when the request fails", async () => {
    await renderLoaded();

    click("enable auto-scroll");
    await act(async () =>
      patchResponse("/api/auto-scroll").reject(new TypeError("offline"))
    );

    expect(
      await screen.findByText("auto-scroll false, shortcuts false")
    ).toBeInTheDocument();
    expect(mockToastError).toHaveBeenCalledWith("Failed to save preferences");
  });

  it("keeps the saved change when an older /api/me response lands later", async () => {
    await renderLoaded();
    const staleMe = deferred<Response>();
    meResponses.push(staleMe.promise);

    click("refresh");
    click("enable auto-scroll");
    // It differs from the cached user, so applying it would re-render.
    await act(async () =>
      staleMe.resolve(
        meResponse({ auto_scroll: false, shortcut_enabled: true })
      )
    );
    serverPreferences = { auto_scroll: true, shortcut_enabled: false };
    await act(async () =>
      patchResponse("/api/auto-scroll").resolve(new Response(null))
    );

    await waitFor(() =>
      expect(
        screen.getByText("auto-scroll true, shortcuts false")
      ).toBeInTheDocument()
    );
  });
});
