import { renderHook } from "@tests/setup/test-utils";
import { useChatShortcutActions } from "@/lib/shortcuts/hooks";

const mockSetAppMode = jest.fn();
const mockReset = jest.fn();
let mockSavedMode: "AUTO" | "CHAT" | "SEARCH" = "CHAT";

jest.mock("@/providers/QueryControllerProvider", () => ({
  useQueryController: () => ({
    reset: mockReset,
    setAppMode: mockSetAppMode,
  }),
}));
jest.mock("@/providers/UserProvider", () => ({
  useUser: () => ({
    user: { preferences: { default_app_mode: mockSavedMode } },
  }),
}));
jest.mock("@/hooks/useChatSessions", () => ({
  __esModule: true,
  default: () => ({ chatSessions: [] }),
}));
jest.mock("@/lib/navigation/hooks", () => ({
  useAppPosition: () => ({
    isNewSession: () => true,
    chat: () => null,
    openNewSession: jest.fn(),
    openChat: jest.fn(),
  }),
}));

test.each([
  ["AUTO", "auto"],
  ["SEARCH", "search"],
  ["CHAT", "chat"],
] as const)(
  "New Session on an idle composer keeps the saved %s mode",
  (saved, mode) => {
    mockSavedMode = saved;
    const { result } = renderHook(() => useChatShortcutActions());
    result.current.newChat();
    expect(mockSetAppMode).toHaveBeenLastCalledWith(mode);
  }
);
