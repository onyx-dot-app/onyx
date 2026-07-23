import { renderHook, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { User, UserPersonalization } from "@/lib/types";

function makeUser(personalization: Partial<UserPersonalization>): User {
  return {
    personalization: {
      name: "Bob",
      role: "Engineer",
      memories: [],
      use_memories: false,
      enable_memory_tool: false,
      user_preferences: "",
      ...personalization,
    },
  } as unknown as User;
}

describe("useUserPersonalization", () => {
  it("persists only the fields the caller changed, not the whole snapshot", async () => {
    const persist = jest.fn().mockResolvedValue(undefined);
    const user = makeUser({});

    const { result } = renderHook(() => useUserPersonalization(user, persist));

    await act(async () => {
      await result.current.handleSavePersonalization({ use_memories: true });
    });

    expect(persist).toHaveBeenCalledTimes(1);
    // The payload must contain ONLY the changed field so independent saves
    // commute on the backend (which leaves omitted fields untouched). Sending
    // the full snapshot lets a stale save clobber another field's change.
    expect(persist).toHaveBeenCalledWith({ use_memories: true });
  });

  it("does not resend unrelated fields when saving name", async () => {
    const persist = jest.fn().mockResolvedValue(undefined);
    const user = makeUser({ memories: [{ id: 1, content: "keep me" }] });

    const { result } = renderHook(() => useUserPersonalization(user, persist));

    await act(async () => {
      await result.current.handleSavePersonalization({ name: "Bobby" });
    });

    const payload = persist.mock.calls[0]![0] as Partial<UserPersonalization>;
    expect(payload).toEqual({ name: "Bobby" });
    expect(payload).not.toHaveProperty("memories");
    expect(payload).not.toHaveProperty("role");
  });

  it("trims memories before persisting when memories are the changed field", async () => {
    const persist = jest.fn().mockResolvedValue(undefined);
    const user = makeUser({});

    const { result } = renderHook(() => useUserPersonalization(user, persist));

    await act(async () => {
      await result.current.handleSavePersonalization({
        memories: [
          { id: 1, content: "  trimmed  " },
          { id: 2, content: "   " },
        ],
      });
    });

    expect(persist).toHaveBeenCalledWith({
      memories: [{ id: 1, content: "trimmed" }],
    });
  });
});
