import { renderHook, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { useCallback, useEffect, useRef } from "react";
import { useDraft, draftKey, clearDraft } from "@/hooks/useDraft";

const KEY = draftKey("test", "1");

describe("useDraft", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    sessionStorage.clear();
  });

  afterEach(() => {
    act(() => {
      jest.runOnlyPendingTimers();
    });
    jest.useRealTimers();
  });

  it("debounces writes to storage", () => {
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    act(() => {
      result.current.save("hello");
    });
    expect(sessionStorage.getItem(KEY)).toBeNull();

    act(() => {
      jest.advanceTimersByTime(300);
    });
    expect(JSON.parse(sessionStorage.getItem(KEY)!)).toBe("hello");
  });

  it("collapses rapid writes into a single trailing write", () => {
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    act(() => {
      result.current.save("a");
      result.current.save("ab");
      result.current.save("abc");
    });
    act(() => {
      jest.advanceTimersByTime(300);
    });
    expect(JSON.parse(sessionStorage.getItem(KEY)!)).toBe("abc");
  });

  it("restores an existing draft on mount", () => {
    sessionStorage.setItem(KEY, JSON.stringify("saved"));

    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    expect(result.current.loaded).toBe(true);
    expect(result.current.draft).toBe("saved");
    expect(result.current.hasDraft).toBe(true);
  });

  it("reports no draft when storage is empty", () => {
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    expect(result.current.loaded).toBe(true);
    expect(result.current.draft).toBeNull();
    expect(result.current.hasDraft).toBe(false);
  });

  it("clear() removes the draft and cancels a pending write", () => {
    sessionStorage.setItem(KEY, JSON.stringify("saved"));
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    act(() => {
      result.current.save("new value");
      result.current.clear();
    });
    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(sessionStorage.getItem(KEY)).toBeNull();
    expect(result.current.draft).toBeNull();
  });

  it("skips empty and whitespace-only values, removing any existing key", () => {
    sessionStorage.setItem(KEY, JSON.stringify("saved"));
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    act(() => {
      result.current.save("   ");
    });
    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("does not restore a whitespace-only stored value", () => {
    sessionStorage.setItem(KEY, JSON.stringify("   "));
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    expect(result.current.hasDraft).toBe(false);
  });

  it("isolates drafts stored under different keys", () => {
    const keyA = draftKey("test", "a");
    const keyB = draftKey("test", "b");
    sessionStorage.setItem(keyA, JSON.stringify("value-a"));
    sessionStorage.setItem(keyB, JSON.stringify("value-b"));

    const { result: resultA } = renderHook(() =>
      useDraft<string>({ key: keyA })
    );
    const { result: resultB } = renderHook(() =>
      useDraft<string>({ key: keyB })
    );

    expect(resultA.current.draft).toBe("value-a");
    expect(resultB.current.draft).toBe("value-b");
  });

  it("cancels a pending write when the key changes, never writing under the old key", () => {
    const keyA = draftKey("test", "a");
    const keyB = draftKey("test", "b");
    const { result, rerender } = renderHook(
      ({ key }) => useDraft<string>({ key }),
      { initialProps: { key: keyA } }
    );

    act(() => {
      result.current.save("typed under a");
    });
    rerender({ key: keyB });
    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(sessionStorage.getItem(keyA)).toBeNull();
    expect(sessionStorage.getItem(keyB)).toBeNull();
  });

  it("re-reads when the key changes", () => {
    const keyA = draftKey("test", "a");
    const keyB = draftKey("test", "b");
    sessionStorage.setItem(keyA, JSON.stringify("value-a"));
    sessionStorage.setItem(keyB, JSON.stringify("value-b"));

    const { result, rerender } = renderHook(
      ({ key }) => useDraft<string>({ key }),
      { initialProps: { key: keyA } }
    );
    expect(result.current.draft).toBe("value-a");

    rerender({ key: keyB });
    expect(result.current.draft).toBe("value-b");
  });

  // Consumers rely on this edge to re-seed; a key change must drop loaded to
  // false.
  it("drops loaded to false on the render right after the key changes", () => {
    const keyA = draftKey("test", "a");
    const keyB = draftKey("test", "b");

    const loadedHistory: boolean[] = [];
    const { rerender } = renderHook(
      ({ key }) => {
        const r = useDraft<string>({ key });
        loadedHistory.push(r.loaded);
        return r;
      },
      { initialProps: { key: keyA } }
    );

    loadedHistory.length = 0; // ignore mount
    rerender({ key: keyB });

    expect(loadedHistory).toContain(false);
    expect(loadedHistory[loadedHistory.length - 1]).toBe(true);
  });

  // Mirrors AppInputBar's loaded-edge save gating across a key flip.
  it("still persists after a key change under loaded-edge save gating", () => {
    const keyA = draftKey("chat", "new");
    const keyB = draftKey("chat", "123");

    function useGatedDraft(key: string) {
      const { loaded, draft, save } = useDraft<string>({ key });
      const seededRef = useRef(false);
      useEffect(() => {
        seededRef.current = false;
      }, [key]);
      useEffect(() => {
        if (!loaded || seededRef.current) return;
        seededRef.current = true;
      }, [loaded, draft]);
      const trySave = useCallback(
        (value: string) => {
          if (!loaded || !seededRef.current) return;
          save(value);
        },
        [loaded, save]
      );
      return { trySave };
    }

    const { result, rerender } = renderHook(({ key }) => useGatedDraft(key), {
      initialProps: { key: keyA },
    });

    rerender({ key: keyB });

    act(() => {
      result.current.trySave("draft-for-b");
    });
    act(() => {
      jest.advanceTimersByTime(300);
    });

    expect(JSON.parse(sessionStorage.getItem(keyB)!)).toBe("draft-for-b");
  });

  it("clear() drops a persisted draft immediately, not on the debounce", () => {
    const { result } = renderHook(() => useDraft<string>({ key: KEY }));

    act(() => {
      result.current.save("queued message");
    });
    act(() => {
      jest.advanceTimersByTime(300);
    });
    expect(sessionStorage.getItem(KEY)).not.toBeNull();

    act(() => {
      result.current.save("");
      result.current.clear();
    });

    expect(sessionStorage.getItem(KEY)).toBeNull();
  });

  it("survives storage access throwing (blocked/SSR-like environments)", () => {
    const getItemSpy = jest
      .spyOn(Storage.prototype, "getItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });
    const setItemSpy = jest
      .spyOn(Storage.prototype, "setItem")
      .mockImplementation(() => {
        throw new Error("blocked");
      });

    const { result } = renderHook(() => useDraft<string>({ key: KEY }));
    expect(result.current.draft).toBeNull();
    expect(result.current.loaded).toBe(true);

    act(() => {
      result.current.save("hello");
    });
    expect(() =>
      act(() => {
        jest.advanceTimersByTime(300);
      })
    ).not.toThrow();

    getItemSpy.mockRestore();
    setItemSpy.mockRestore();
  });

  it("clearDraft helper removes a key directly", () => {
    sessionStorage.setItem(KEY, JSON.stringify("saved"));
    clearDraft(KEY);
    expect(sessionStorage.getItem(KEY)).toBeNull();
  });
});
