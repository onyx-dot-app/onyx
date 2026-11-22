import { renderHook } from "@tests/setup/test-utils";
import { useAppPosition } from "@/lib/navigation/hooks";

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
