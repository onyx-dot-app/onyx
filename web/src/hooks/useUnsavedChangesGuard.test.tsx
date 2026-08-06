import { act, cleanup, renderHook } from "@testing-library/react";
import useUnsavedChangesGuard from "@/hooks/useUnsavedChangesGuard";
import {
  UnsavedChangesNavigationProvider,
  useUnsavedChangesNavigation,
} from "@/providers/UnsavedChangesNavigationProvider";

const mockPush = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ push: mockPush }),
}));

describe("useUnsavedChangesGuard", () => {
  afterEach(() => {
    cleanup();
    jest.restoreAllMocks();
    mockPush.mockReset();
    document.body.replaceChildren();
  });

  it("warns before unloading only while dirty", () => {
    const { rerender } = renderHook(
      ({ isDirty }) => useUnsavedChangesGuard({ isDirty }),
      { initialProps: { isDirty: true } }
    );

    const dirtyEvent = new Event("beforeunload", { cancelable: true });
    act(() => window.dispatchEvent(dirtyEvent));
    expect(dirtyEvent.defaultPrevented).toBe(true);

    rerender({ isDirty: false });
    const cleanEvent = new Event("beforeunload", { cancelable: true });
    act(() => window.dispatchEvent(cleanEvent));
    expect(cleanEvent.defaultPrevented).toBe(false);
  });

  it("defers requested navigation until discard is confirmed", () => {
    const navigate = jest.fn();
    const onDiscard = jest.fn();
    const { result } = renderHook(() =>
      useUnsavedChangesGuard({ isDirty: true, onDiscard })
    );

    act(() => result.current.requestLeave(navigate));
    expect(result.current.confirmationOpen).toBe(true);
    expect(navigate).not.toHaveBeenCalled();

    act(() => result.current.discardAndLeave());
    expect(onDiscard).toHaveBeenCalledTimes(1);
    expect(navigate).toHaveBeenCalledTimes(1);
    expect(result.current.confirmationOpen).toBe(false);
  });

  it("guards navigation requested by another component", () => {
    const navigate = jest.fn();
    const { result } = renderHook(
      () => ({
        guard: useUnsavedChangesGuard({ isDirty: true }),
        navigation: useUnsavedChangesNavigation(),
      }),
      { wrapper: UnsavedChangesNavigationProvider }
    );

    act(() => result.current.navigation.requestNavigation(navigate));
    expect(result.current.guard.confirmationOpen).toBe(true);
    expect(navigate).not.toHaveBeenCalled();

    act(() => result.current.guard.discardAndLeave());
    expect(navigate).toHaveBeenCalledTimes(1);
  });

  it("cancels pending navigation without discarding changes", () => {
    const navigate = jest.fn();
    const onDiscard = jest.fn();
    const { result } = renderHook(() =>
      useUnsavedChangesGuard({ isDirty: true, onDiscard })
    );

    act(() => result.current.requestLeave(navigate));
    act(() => result.current.cancelLeave());
    expect(result.current.confirmationOpen).toBe(false);
    expect(onDiscard).not.toHaveBeenCalled();
    expect(navigate).not.toHaveBeenCalled();
  });

  it("guards unmodified internal link clicks", () => {
    const { result } = renderHook(() =>
      useUnsavedChangesGuard({ isDirty: true })
    );
    const link = document.createElement("a");
    link.href = "/target?tab=one#section";
    document.body.append(link);

    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
    });
    act(() => link.dispatchEvent(event));

    expect(event.defaultPrevented).toBe(true);
    expect(result.current.confirmationOpen).toBe(true);
    expect(mockPush).not.toHaveBeenCalled();

    act(() => result.current.discardAndLeave());
    expect(mockPush).toHaveBeenCalledWith("/target?tab=one#section");
  });
});
