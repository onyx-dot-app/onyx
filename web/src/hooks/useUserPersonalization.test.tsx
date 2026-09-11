import { act, renderHook } from "@testing-library/react";
import useUserPersonalization from "@/hooks/useUserPersonalization";
import { User, UserPersonalization } from "@/lib/types";

function makeUser(personalization: Partial<UserPersonalization>): User {
  return {
    personalization: {
      name: "",
      role: "",
      memories: [],
      use_memories: true,
      enable_memory_tool: true,
      user_preferences: "",
      ...personalization,
    },
  } as unknown as User;
}

describe("useUserPersonalization", () => {
  test("does not clobber unsaved local edits when the user object reference changes but its personalization content is unchanged", async () => {
    const persist = jest.fn().mockResolvedValue(undefined);
    const user1 = makeUser({ name: "Alice" });

    const { result, rerender } = renderHook(
      ({ user }) => useUserPersonalization(user, persist),
      { initialProps: { user: user1 } }
    );

    // User types a new name but has not yet triggered a save (e.g. has not blurred).
    act(() => {
      result.current.updatePersonalizationField("name", "Alice Smith");
    });
    expect(result.current.personalizationValues.name).toBe("Alice Smith");

    // An unrelated settings save (theme, auto-scroll, etc.) calls refreshUser(),
    // which makes SWR hand back a brand-new `user` object reference whose
    // personalization content is identical to before.
    const user2 = makeUser({ name: "Alice" });
    rerender({ user: user2 });

    // The in-progress edit must survive the reference churn.
    expect(result.current.personalizationValues.name).toBe("Alice Smith");
  });

  test("adopts genuinely changed server personalization", () => {
    const persist = jest.fn().mockResolvedValue(undefined);
    const { result, rerender } = renderHook(
      ({ user }) => useUserPersonalization(user, persist),
      { initialProps: { user: makeUser({ name: "Alice" }) } }
    );

    // No local edit; server pushes a real change (e.g. memory generated elsewhere).
    rerender({
      user: makeUser({ name: "Alice", user_preferences: "be terse" }),
    });

    expect(result.current.personalizationValues.user_preferences).toBe(
      "be terse"
    );
  });
});
