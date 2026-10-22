import { renderHook } from "@tests/setup/test-utils";
import { useAppPosition } from "@/lib/position/hooks";

let mockPathname = "/app";
let mockParams = new URLSearchParams();
const mockRouter = { push: jest.fn(), replace: jest.fn() };

jest.mock("next/navigation", () => ({
  usePathname: () => mockPathname,
  useSearchParams: () => mockParams,
  useRouter: () => mockRouter,
}));

beforeEach(() => {
  mockPathname = "/app";
  mockParams = new URLSearchParams();
});

test.each(["/app/plugins", "/app/plugins/oauth/complete"])(
  "recognizes %s without highlighting New chat",
  (pathname) => {
    mockPathname = pathname;
    mockParams = new URLSearchParams("chatId=existing-chat");
    const { result } = renderHook(() => useAppPosition());
    expect(result.current.isPlugins()).toBe(true);
    expect(result.current.isNewSession()).toBe(false);
    expect(result.current.isChat()).toBe(false);
    expect(result.current.href()).toBe("/app/plugins");
  }
);

test("keeps conversation routing separate from Plugins", () => {
  mockParams = new URLSearchParams("chatId=existing-chat");
  const { result } = renderHook(() => useAppPosition());
  expect(result.current.isPlugins()).toBe(false);
  expect(result.current.chat()).toBe("existing-chat");
  expect(result.current.href()).toBe("/app?chatId=existing-chat");
});
