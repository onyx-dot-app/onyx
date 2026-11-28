import { fireEvent, render, renderHook, screen } from "@tests/setup/test-utils";
import { useAppPosition } from "@/lib/navigation/hooks";
import { useChatSessionStore } from "@/app/app/stores/useChatSessionStore";

let mockPathname = "/app";
let mockParams = new URLSearchParams();
const mockRouter = { push: jest.fn(), replace: jest.fn() };

jest.mock("next/navigation", () => ({
  ...jest.requireActual<typeof import("@tests/setup/mocks/nextNavigation")>(
    "@tests/setup/mocks/nextNavigation"
  ).nextNavigationMock,
  usePathname: () => mockPathname,
  useSearchParams: () => mockParams,
  useRouter: () => mockRouter,
}));

beforeEach(() => {
  mockPathname = "/app";
  mockParams = new URLSearchParams();
});

test.each(["/app/customize", "/app/customize/skills/7"])(
  "recognizes %s without highlighting New chat",
  (pathname) => {
    mockPathname = pathname;
    mockParams = new URLSearchParams("chatId=existing-chat");
    const { result } = renderHook(() => useAppPosition());
    expect(result.current.isCustomize()).toBe(true);
    expect(result.current.isNewSession()).toBe(false);
    expect(result.current.isChat()).toBe(false);
    expect(result.current.href()).toBe("/app/customize");
  }
);

test.each(["/app/scheduled-tasks", "/app/scheduled-tasks/task-1/edit"])(
  "recognizes %s as Scheduled Tasks",
  (pathname) => {
    mockPathname = pathname;
    const { result } = renderHook(() => useAppPosition());
    expect(result.current.isScheduledTasks()).toBe(true);
    expect(result.current.isNewSession()).toBe(false);
    expect(result.current.href()).toBe("/app/scheduled-tasks");
  }
);

test("keeps conversation routing separate from Customize", () => {
  mockParams = new URLSearchParams("chatId=existing-chat");
  const { result } = renderHook(() => useAppPosition());
  expect(result.current.isCustomize()).toBe(false);
  expect(result.current.chat()).toBe("existing-chat");
  expect(result.current.href()).toBe("/app?chatId=existing-chat");
});

describe("going to a new session while a sent chat's URL is not rendered yet", () => {
  // A send from a new session makes its chat current and writes its URL; the
  // page still renders the new session until that URL lands.
  beforeEach(() => {
    window.history.replaceState(null, "", "/app?chatId=sent-chat");
    useChatSessionStore.getState().setCurrentSession("sent-chat");
  });
  afterEach(() => {
    useChatSessionStore.setState({
      sessions: new Map(),
      currentSessionId: null,
    });
    window.history.replaceState(null, "", "/");
  });

  test("openNewSession clears the sent chat", () => {
    const { result } = renderHook(() => useAppPosition());
    result.current.openNewSession();
    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
    expect(window.location.search).toBe("");
  });

  test("a click on the new-session link clears the sent chat", () => {
    const { result } = renderHook(() => useAppPosition());
    render(<a {...result.current.linkToNewSession()}>New Session</a>);
    fireEvent.click(screen.getByText("New Session"));
    expect(useChatSessionStore.getState().currentSessionId).toBeNull();
  });

  test("leaves a rendered chat to the page", () => {
    mockParams = new URLSearchParams("chatId=sent-chat");
    const { result } = renderHook(() => useAppPosition());
    result.current.openNewSession();
    expect(useChatSessionStore.getState().currentSessionId).toBe("sent-chat");
  });
});
