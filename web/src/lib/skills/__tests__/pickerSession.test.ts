import {
  reduceOnInput,
  reduceOnSelection,
  reduceOnDismiss,
  INITIAL_PICKER_SESSION,
  type PickerSession,
} from "@/lib/skills/pickerSession";

const open = (slashIndex: number, query: string): PickerSession => ({
  slashIndex,
  suppressed: false,
  open: true,
  query,
});

describe("reduceOnInput", () => {
  it("opens a session when a slash trigger is typed", () => {
    expect(reduceOnInput(INITIAL_PICKER_SESSION, "/")).toEqual({
      slashIndex: 0,
      suppressed: false,
      open: true,
      query: "",
    });
  });

  it("extends the query as the token grows", () => {
    expect(reduceOnInput(open(0, "comp"), "/company")).toEqual(
      open(0, "company")
    );
  });

  it("returns the same reference when the open token is unchanged", () => {
    const state = open(0, "comp");
    expect(reduceOnInput(state, "/comp")).toBe(state);
  });

  it("does not open while typing plain text (no churn)", () => {
    expect(reduceOnInput(INITIAL_PICKER_SESSION, "hello")).toBe(
      INITIAL_PICKER_SESSION
    );
  });

  it("keeps a suppressed session closed while typing more of the token", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "comp",
    };
    expect(reduceOnInput(suppressed, "/company")).toBe(suppressed);
  });

  it("keeps a suppressed session alive across a space while its slash survives", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "company",
    };
    // "/company " has no active trigger (whitespace in the query) but the slash
    // at index 0 survives, so the session is preserved (not reset).
    expect(reduceOnInput(suppressed, "/company ")).toBe(suppressed);
  });

  it("does NOT reopen when backspacing from a space into a suppressed token", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "company",
    };
    // The regression: space then backspace must not re-arm the same slash.
    expect(reduceOnInput(suppressed, "/company")).toBe(suppressed);
  });

  it("fully resets once the tracked slash is deleted", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "comp",
    };
    expect(reduceOnInput(suppressed, "comp")).toBe(INITIAL_PICKER_SESSION);
  });

  it("re-arms (clears suppression) when a NEW slash token is typed", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "company",
    };
    expect(reduceOnInput(suppressed, "/company /pp")).toEqual({
      slashIndex: 9,
      suppressed: false,
      open: true,
      query: "pp",
    });
  });

  it("treats a slash shifted by leading edits as a new token", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "comp",
    };
    // Prepending text pushes the slash to index 2; that's a different token.
    expect(reduceOnInput(suppressed, "x /comp")).toEqual({
      slashIndex: 2,
      suppressed: false,
      open: true,
      query: "comp",
    });
  });

  it("treats null text-before-cursor as no trigger and resets", () => {
    expect(reduceOnInput(open(0, "comp"), null)).toBe(INITIAL_PICKER_SESSION);
  });
});

describe("reduceOnSelection", () => {
  it("never opens the picker from a caret move", () => {
    expect(reduceOnSelection(INITIAL_PICKER_SESSION, "/comp")).toBe(
      INITIAL_PICKER_SESSION
    );
  });

  it("syncs the query when the caret stays within the open token", () => {
    expect(reduceOnSelection(open(0, "company"), "/comp")).toEqual(
      open(0, "comp")
    );
  });

  it("returns the same reference when the query is unchanged", () => {
    const state = open(0, "comp");
    expect(reduceOnSelection(state, "/comp")).toBe(state);
  });

  it("closes when the caret leaves the tracked token", () => {
    expect(reduceOnSelection(open(0, "comp"), "/comp other")).toBe(
      INITIAL_PICKER_SESSION
    );
  });

  it("closes when the caret moves to a different slash token", () => {
    expect(reduceOnSelection(open(0, "comp"), "/comp /pp")).toBe(
      INITIAL_PICKER_SESSION
    );
  });
});

describe("reduceOnDismiss", () => {
  it("hides the picker and marks the token suppressed", () => {
    expect(reduceOnDismiss(open(0, "comp"))).toEqual({
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "comp",
    });
  });

  it("is a no-op when already closed and suppressed", () => {
    const suppressed: PickerSession = {
      slashIndex: 0,
      suppressed: true,
      open: false,
      query: "comp",
    };
    expect(reduceOnDismiss(suppressed)).toBe(suppressed);
  });
});
