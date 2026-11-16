import {
  reduceOnInput,
  reduceOnEscape,
  INITIAL_PICKER_SESSION,
  type PickerSession,
} from "@/lib/skills/pickerSession";
import type { PickerSections } from "@/lib/skills/picker";

const SECTIONS: PickerSections = {
  skills: [{ kind: "skill", slug: "foo", name: "foo", description: "" }],
  apps: [],
  mcpServers: [],
};
const anything = () => SECTIONS;

/** The text with the caret at its end. */
const atEnd = (before: string) => ({ before, after: "" });

const open = (
  triggerIndex: number,
  query: string,
  trigger = "/"
): PickerSession => ({
  triggerIndex,
  suppressed: false,
  open: true,
  query,
  token: { before: `${trigger}${query}`, after: "" },
  sections: SECTIONS,
});

const suppressed = (triggerIndex: number, query: string): PickerSession => ({
  ...open(triggerIndex, query),
  suppressed: true,
  open: false,
});

describe("reduceOnInput", () => {
  it("opens a session when a slash trigger is typed", () => {
    expect(
      reduceOnInput(INITIAL_PICKER_SESSION, atEnd("/"), "/", anything)
    ).toEqual(open(0, ""));
  });

  it("extends the query as the token grows", () => {
    expect(
      reduceOnInput(open(0, "comp"), atEnd("/company"), "/", anything)
    ).toEqual(open(0, "company"));
  });

  it("queries the whole word and splits the token at the caret", () => {
    expect(
      reduceOnInput(
        INITIAL_PICKER_SESSION,
        { before: "hi /co", after: "mpany now" },
        "/",
        anything
      )
    ).toEqual({
      ...open(3, "company"),
      token: { before: "/co", after: "mpany" },
    });
  });

  it("ends the session when the word matches nothing", () => {
    const hasMatches = (query: string): PickerSections =>
      "foo".startsWith(query)
        ? SECTIONS
        : { skills: [], apps: [], mcpServers: [] };
    expect(
      reduceOnInput(open(0, "foo", "@"), atEnd("@foox"), "@", hasMatches)
    ).toBe(INITIAL_PICKER_SESSION);
    // `@fo|bar`: the query is the whole word, so `fo` alone does not match.
    expect(
      reduceOnInput(
        INITIAL_PICKER_SESSION,
        { before: "@fo", after: "bar" },
        "@",
        hasMatches
      )
    ).toBe(INITIAL_PICKER_SESSION);
    // Deleting back to a matching word opens it again.
    expect(
      reduceOnInput(INITIAL_PICKER_SESSION, atEnd("@foo"), "@", hasMatches)
    ).toEqual(open(0, "foo", "@"));
  });

  it("does not open while typing plain text (no churn)", () => {
    expect(
      reduceOnInput(INITIAL_PICKER_SESSION, atEnd("hello"), "/", anything)
    ).toBe(INITIAL_PICKER_SESSION);
  });

  it("does not open with the caret before the trigger", () => {
    expect(
      reduceOnInput(
        INITIAL_PICKER_SESSION,
        { before: "", after: "/comp" },
        "/",
        anything
      )
    ).toBe(INITIAL_PICKER_SESSION);
  });

  it("keeps a suppressed session closed while typing more of the token", () => {
    const state = suppressed(0, "comp");
    expect(reduceOnInput(state, atEnd("/company"), "/", anything)).toBe(state);
  });

  it("keeps a suppressed session alive across a space while its slash survives", () => {
    const state = suppressed(0, "company");
    // "/company " has no active trigger (whitespace in the query) but the slash
    // at index 0 survives, so the session is preserved (not reset).
    expect(reduceOnInput(state, atEnd("/company "), "/", anything)).toBe(state);
  });

  it("does NOT reopen when backspacing from a space into a suppressed token", () => {
    const state = suppressed(0, "company");
    expect(reduceOnInput(state, atEnd("/company"), "/", anything)).toBe(state);
  });

  it("fully resets once the tracked slash is deleted", () => {
    expect(
      reduceOnInput(suppressed(0, "comp"), atEnd("comp"), "/", anything)
    ).toBe(INITIAL_PICKER_SESSION);
  });

  it("re-arms (clears suppression) when a NEW slash token is typed", () => {
    expect(
      reduceOnInput(
        suppressed(0, "company"),
        atEnd("/company /pp"),
        "/",
        anything
      )
    ).toEqual(open(9, "pp"));
  });

  it("treats a slash shifted by leading edits as a new token", () => {
    // Prepending text pushes the slash to index 2; that's a different token.
    expect(
      reduceOnInput(suppressed(0, "comp"), atEnd("x /comp"), "/", anything)
    ).toEqual(open(2, "comp"));
  });

  it("treats null text as no trigger and resets", () => {
    expect(reduceOnInput(open(0, "comp"), null, "/", anything)).toBe(
      INITIAL_PICKER_SESSION
    );
  });
});

describe("reduceOnEscape", () => {
  it("hides the picker and marks the token suppressed", () => {
    expect(reduceOnEscape(open(0, "comp"))).toEqual(suppressed(0, "comp"));
  });

  it("is a no-op when already closed and suppressed", () => {
    const state = suppressed(0, "comp");
    expect(reduceOnEscape(state)).toBe(state);
  });
});

describe("with a `@` trigger", () => {
  it("opens on `@` and tracks its query", () => {
    expect(
      reduceOnInput(INITIAL_PICKER_SESSION, atEnd("hi @rev"), "@", anything)
    ).toEqual(open(3, "rev", "@"));
  });

  it("resets once the tracked `@` is gone", () => {
    expect(
      reduceOnInput(suppressed(3, "rev"), atEnd("hi "), "@", anything)
    ).toBe(INITIAL_PICKER_SESSION);
  });
});
