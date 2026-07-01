import { renderHook } from "@testing-library/react";
import type { NotificationsResponse } from "@/lib/notifications/interfaces";
import { NotificationType } from "@/lib/notifications/interfaces";
import useNotifications from "./useNotifications";

const mockUseSWRInfinite = jest.fn();

jest.mock("swr/infinite", () => ({
  __esModule: true,
  default: (...args: unknown[]) => mockUseSWRInfinite(...args),
}));

jest.mock("swr", () => ({
  __esModule: true,
  ...jest.requireActual("swr"),
  useSWRConfig: () => ({ mutate: jest.fn() }),
}));

function makePage(
  overrides: Partial<NotificationsResponse>
): NotificationsResponse {
  return {
    notifications: [],
    total_items: 0,
    undismissed_count: 0,
    page_num: 0,
    page_size: 25,
    has_more: false,
    ...overrides,
  };
}

function notification(id: number) {
  return {
    id,
    notif_type: NotificationType.REINDEX,
    title: `notification ${id}`,
    description: null,
    dismissed: false,
    first_shown: "2026-01-01T00:00:00Z",
    last_shown: "2026-01-01T00:00:00Z",
  };
}

function mockInfinite(data: unknown) {
  mockUseSWRInfinite.mockReturnValue({
    data,
    error: undefined,
    mutate: jest.fn(),
    size: Array.isArray(data) ? data.length : 0,
    setSize: jest.fn(),
  });
}

describe("useNotifications", () => {
  beforeEach(() => {
    jest.clearAllMocks();
  });

  // Regression for #12591: the notifications API returning a page whose
  // `notifications` field is not an array must not throw. This hook feeds
  // always-mounted UI (sidebar, notifications popover), so a throw here
  // black-screens the app instead of degrading gracefully.
  it.each<[string, unknown]>([
    ["an object", {}],
    ["a string", "unexpected"],
    ["null", null],
    ["undefined", undefined],
  ])("returns [] without throwing when a page's notifications is %s", (_, value) => {
    mockInfinite([makePage({ notifications: value as never })]);

    const { result } = renderHook(() => useNotifications());

    expect(result.current.notifications).toEqual([]);
  });

  it("skips a malformed page but still returns notifications from valid pages", () => {
    mockInfinite([
      makePage({ notifications: [notification(1)] }),
      makePage({ notifications: {} as never }),
      makePage({ notifications: [notification(2)] }),
    ]);

    const { result } = renderHook(() => useNotifications());

    expect(result.current.notifications.map((n) => n.id)).toEqual([1, 2]);
  });

  it("de-duplicates notifications across pages for a valid response", () => {
    mockInfinite([
      makePage({ notifications: [notification(1), notification(2)] }),
      makePage({ notifications: [notification(2), notification(3)] }),
    ]);

    const { result } = renderHook(() => useNotifications());

    expect(result.current.notifications.map((n) => n.id)).toEqual([1, 2, 3]);
  });
});
