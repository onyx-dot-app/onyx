import { render, screen, setupUser } from "@tests/setup/test-utils";
import { InputDatePicker } from "@opal/components";

function renderEmpty() {
  const onChange = jest.fn();
  render(<InputDatePicker value={null} onChange={onChange} />);
  return {
    onChange,
    month: screen.getByLabelText<HTMLInputElement>("Month"),
    day: screen.getByLabelText<HTMLInputElement>("Day"),
    year: screen.getByLabelText<HTMLInputElement>("Year"),
  };
}

// ---------------------------------------------------------------------------
// Typing
// ---------------------------------------------------------------------------

describe("typing", () => {
  it("fills each segment in turn and commits on Enter", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.month);
    await user.keyboard("10192026{Enter}");
    expect(fields.onChange).toHaveBeenCalledWith(new Date(2026, 9, 19));
  });

  it("keeps the day when separators follow full parts", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.month);
    await user.keyboard("10/19/2026{Enter}");
    expect(fields.day).toHaveValue("19");
    expect(fields.onChange).toHaveBeenCalledWith(new Date(2026, 9, 19));
  });

  it("moves on when a separator follows a one-digit part", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.month);
    await user.keyboard("1/2-2026{Enter}");
    expect(fields.month).toHaveValue("01");
    expect(fields.day).toHaveValue("02");
    expect(fields.onChange).toHaveBeenCalledWith(new Date(2026, 0, 2));
  });

  it("moves the digits after the caret into the next segment", async () => {
    const user = setupUser();
    render(<InputDatePicker value={null} onChange={() => {}} />);
    const month = screen.getByLabelText<HTMLInputElement>("Month");
    await user.click(month);
    await user.keyboard("12");
    await user.type(month, "/", {
      initialSelectionStart: 1,
      initialSelectionEnd: 1,
    });
    const day = screen.getByLabelText<HTMLInputElement>("Day");
    expect(month).toHaveValue("01");
    expect(day).toHaveValue("2");
    expect(day).toHaveFocus();
    // The caret sits just after the separator, ahead of the moved digits.
    expect(day.selectionStart).toBe(0);
  });

  it("blocks digits beyond a full segment", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.year);
    await user.keyboard("202612");
    expect(fields.year).toHaveValue("2026");
  });

  it("ignores letters and a separator in the year", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.year);
    await user.keyboard("2a0/2b6");
    expect(fields.year).toHaveValue("2026");
  });

  it("reads Arabic-Indic digits", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.month);
    await user.keyboard("\u0661\u0662");
    expect(fields.month).toHaveValue("12");
    expect(fields.day).toHaveFocus();
  });
});

// ---------------------------------------------------------------------------
// Pasting
// ---------------------------------------------------------------------------

describe("pasting", () => {
  it.each([
    ["month", "10/19/2026"],
    ["day", "10-19-2026"],
    ["year", "10.19.2026"],
    ["month", "2026-10-19"],
    ["month", " \u200F10/19/2026 "],
    ["month", "\u0661\u0660/\u0661\u0669/\u0662\u0660\u0662\u0666"],
  ] as const)(
    "into the %s segment, %s fills every segment",
    async (segment, text) => {
      const user = setupUser();
      const fields = renderEmpty();
      await user.click(fields[segment]);
      await user.paste(text);
      expect(fields.month).toHaveValue("10");
      expect(fields.day).toHaveValue("19");
      expect(fields.year).toHaveValue("2026");
    }
  );

  it("pads one-digit parts of a pasted date", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.month);
    await user.paste("1/2/2026");
    expect(fields.month).toHaveValue("01");
    expect(fields.day).toHaveValue("02");
  });

  it("inserts pasted digits into the focused segment, clipped to fit", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.year);
    await user.paste("202612");
    expect(fields.year).toHaveValue("2026");
  });

  it.each(["10/19", "Oct 19 2026", "1/2/26", "10/19/2026/1", "-5"])(
    "ignores %s, which is not a date",
    async (text) => {
      const user = setupUser();
      const fields = renderEmpty();
      for (const field of [fields.month, fields.day, fields.year]) {
        await user.click(field);
        await user.paste(text);
      }
      expect(fields.month).toHaveValue("");
      expect(fields.day).toHaveValue("");
      expect(fields.year).toHaveValue("");
    }
  );

  it("commits a pasted date when focus leaves the field", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.month);
    await user.paste("10/19/2026");
    await user.click(document.body);
    expect(fields.onChange).toHaveBeenCalledWith(new Date(2026, 9, 19));
  });
});

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------

it("Escape on the calendar button returns focus to the first segment", async () => {
  const user = setupUser();
  render(
    <InputDatePicker
      value={new Date(2026, 9, 19)}
      onChange={() => {}}
      clearable
    />
  );

  screen.getByRole("button", { name: "Open calendar" }).focus();
  await user.keyboard("{Escape}");
  expect(screen.getByLabelText("Month")).toHaveFocus();
});
