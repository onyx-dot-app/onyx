import { render, screen, setupUser } from "@tests/setup/test-utils";
import { Button, InputCurrency, getCurrencyParts } from "@opal/components";

// ---------------------------------------------------------------------------
// Display
// ---------------------------------------------------------------------------

describe("display", () => {
  it("pads to the currency's decimals and keeps sub-cent digits", () => {
    const { rerender } = render(
      <InputCurrency value={3} onChange={() => {}} precision={6} />
    );
    expect(screen.getByLabelText("Whole amount")).toHaveValue("3");
    expect(screen.getByLabelText("Fractional amount")).toHaveValue("00");

    rerender(<InputCurrency value={0.075} onChange={() => {}} precision={6} />);
    expect(screen.getByLabelText("Whole amount")).toHaveValue("0");
    expect(screen.getByLabelText("Fractional amount")).toHaveValue("075");
  });

  it("rounds the display half up on decimal digits", () => {
    render(<InputCurrency value={0.075} onChange={() => {}} precision={2} />);
    expect(screen.getByLabelText("Fractional amount")).toHaveValue("08");
  });

  it("shows every stored digit with unlimited precision", () => {
    render(
      <InputCurrency
        value={0.0000001}
        onChange={() => {}}
        precision="unlimited"
      />
    );
    expect(screen.getByLabelText("Whole amount")).toHaveValue("0");
    expect(screen.getByLabelText("Fractional amount")).toHaveValue("0000001");
  });

  it.each([
    ["unlimited", 20],
    [25, 20],
    [Infinity, 20],
    [2.7, 2],
    [Number.NaN, 2],
  ] as const)("accepts %s as %i fraction digits", (precision, digits) => {
    render(
      <InputCurrency value={null} onChange={() => {}} precision={precision} />
    );
    expect(screen.getByLabelText("Fractional amount")).toHaveAttribute(
      "maxLength",
      String(digits)
    );
  });

  it("hides the fraction segment for a negative precision", () => {
    render(<InputCurrency value={3} onChange={() => {}} precision={-1} />);
    expect(screen.queryByLabelText("Fractional amount")).toBeNull();
  });

  it("keeps the number left to right on a right-to-left page", () => {
    render(
      <div dir="rtl">
        <InputCurrency value={12.5} onChange={() => {}} />
      </div>
    );
    expect(
      screen.getByLabelText("Whole amount").closest("[dir]")
    ).toHaveAttribute("dir", "ltr");
  });

  it("rebuilds the segments when the precision drops", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    const { rerender } = render(
      <InputCurrency value={1.25} onChange={onChange} precision={2} />
    );
    rerender(<InputCurrency value={1.25} onChange={onChange} precision={0} />);
    expect(screen.getByLabelText("Whole amount")).toHaveValue("1");
    expect(screen.queryByLabelText("Fractional amount")).toBeNull();

    // The hidden ".25" no longer counts toward the amount.
    await user.clear(screen.getByLabelText("Whole amount"));
    await user.type(screen.getByLabelText("Whole amount"), "2");
    expect(onChange).toHaveBeenLastCalledWith(2);
  });

  it("hides the fraction segment for a zero-decimal currency", () => {
    render(<InputCurrency value={1200} onChange={() => {}} currency="JPY" />);
    expect(screen.getByLabelText("Whole amount")).toHaveValue("1200");
    expect(screen.queryByLabelText("Fractional amount")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// Typing and committing
// ---------------------------------------------------------------------------

describe("typing", () => {
  it("jumps to the fraction on '.' and commits on Enter", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<InputCurrency value={null} onChange={onChange} precision={6} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("3.075");
    expect(screen.getByLabelText("Fractional amount")).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith(3.075);
  });

  it("submits a surrounding form on Enter from either segment", async () => {
    const user = setupUser();
    const onSubmit = jest.fn((e: React.FormEvent) => e.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <InputCurrency value={null} onChange={() => {}} />
        <Button type="submit">Save</Button>
      </form>
    );

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("3{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);

    await user.click(screen.getByLabelText("Fractional amount"));
    await user.keyboard("5{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(2);
  });

  it("steps to the fraction on Enter outside a form", async () => {
    const user = setupUser();
    render(<InputCurrency value={null} onChange={() => {}} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("3{Enter}");
    expect(screen.getByLabelText("Fractional amount")).toHaveFocus();
  });

  it("trims leading zeros as soon as focus leaves the whole segment", async () => {
    const user = setupUser();
    render(<InputCurrency value={null} onChange={() => {}} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("0000{Enter}");
    expect(screen.getByLabelText("Fractional amount")).toHaveFocus();
    expect(screen.getByLabelText("Whole amount")).toHaveValue("0");
  });

  describe("a separator typed mid-number", () => {
    async function typeSeparatorAt(
      caret: number,
      props: Partial<React.ComponentProps<typeof InputCurrency>> = {}
    ) {
      const user = setupUser();
      const onChange = jest.fn();
      render(<InputCurrency value={1234} onChange={onChange} {...props} />);
      await user.type(screen.getByLabelText("Whole amount"), ".", {
        initialSelectionStart: caret,
        initialSelectionEnd: caret,
      });
      return onChange;
    }

    it("moves the digits after the caret into the fraction", async () => {
      const onChange = await typeSeparatorAt(1, { precision: 6 });
      expect(screen.getByLabelText("Whole amount")).toHaveValue("1");
      expect(screen.getByLabelText("Fractional amount")).toHaveValue("234");
      expect(screen.getByLabelText("Fractional amount")).toHaveFocus();
      expect(onChange).toHaveBeenLastCalledWith(1.234);
    });

    it("clips the moved digits to the precision", async () => {
      await typeSeparatorAt(1);
      expect(screen.getByLabelText("Fractional amount")).toHaveValue("23");
    });

    it("fills 0 when the separator goes before every digit", async () => {
      await typeSeparatorAt(0, { precision: 6 });
      expect(screen.getByLabelText("Whole amount")).toHaveValue("0");
      expect(screen.getByLabelText("Fractional amount")).toHaveValue("1234");
    });

    it("keeps every digit when there is no fraction segment", async () => {
      const onChange = await typeSeparatorAt(1, { currency: "JPY" });
      expect(screen.getByLabelText("Whole amount")).toHaveValue("1234");
      expect(onChange).not.toHaveBeenCalled();
    });
  });

  it("blocks fraction digits beyond the precision", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<InputCurrency value={null} onChange={onChange} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("1.999");
    expect(screen.getByLabelText("Fractional amount")).toHaveValue("99");
    expect(onChange).toHaveBeenLastCalledWith(1.99);
  });

  it("keeps a pasted fraction out of a zero-decimal amount", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<InputCurrency value={null} onChange={onChange} currency="JPY" />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.paste("12.50");
    expect(screen.getByLabelText("Whole amount")).toHaveValue("12");
    expect(onChange).toHaveBeenLastCalledWith(12);
  });

  it("reads Arabic-Indic digits", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<InputCurrency value={null} onChange={onChange} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("\u0661\u0662");
    expect(screen.getByLabelText("Whole amount")).toHaveValue("12");
    expect(onChange).toHaveBeenLastCalledWith(12);
  });

  it("splits a pasted amount across both segments", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<InputCurrency value={null} onChange={onChange} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.paste("12.50");
    expect(screen.getByLabelText("Whole amount")).toHaveValue("12");
    expect(screen.getByLabelText("Fractional amount")).toHaveValue("50");
  });

  it("commits null when the field is cleared", async () => {
    const user = setupUser();
    const onChange = jest.fn();
    render(<InputCurrency value={3} onChange={onChange} />);

    await user.clear(screen.getByLabelText("Fractional amount"));
    await user.clear(screen.getByLabelText("Whole amount"));
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith(null);
  });
});

// ---------------------------------------------------------------------------
// Pasting
// ---------------------------------------------------------------------------

describe("pasting", () => {
  function renderEmpty() {
    const onChange = jest.fn();
    render(<InputCurrency value={null} onChange={onChange} />);
    return {
      onChange,
      whole: screen.getByLabelText("Whole amount"),
      fraction: screen.getByLabelText("Fractional amount"),
    };
  }

  it.each([
    ["whole", "1", "1", ""],
    ["fraction", "1", "", "1"],
    ["whole", "1.2", "1", "2"],
    ["fraction", "1.2", "1", "2"],
    ["whole", "$1,234.56", "1234", "56"],
  ] as const)(
    "into the %s segment, %s reads as %s . %s",
    async (segment, text, whole, fraction) => {
      const user = setupUser();
      const fields = renderEmpty();
      await user.click(fields[segment]);
      await user.paste(text);
      expect(fields.whole).toHaveValue(whole);
      expect(fields.fraction).toHaveValue(fraction);
    }
  );

  it.each(["1.2.3", "a1b2c3", "-5"])(
    "ignores %s, which is not an amount",
    async (text) => {
      const user = setupUser();
      const fields = renderEmpty();
      for (const field of [fields.whole, fields.fraction]) {
        await user.click(field);
        await user.paste(text);
      }
      expect(fields.whole).toHaveValue("");
      expect(fields.fraction).toHaveValue("");
      expect(fields.onChange).not.toHaveBeenCalled();
    }
  );

  it("fills 0 when the separator is typed into an empty whole segment", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.whole);
    await user.keyboard(".");
    expect(fields.whole).toHaveValue("0");
    expect(fields.fraction).toHaveFocus();
    expect(fields.onChange).toHaveBeenLastCalledWith(0);
  });

  it("fills 0 when a pasted amount starts with the separator", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.fraction);
    await user.paste(".5");
    expect(fields.whole).toHaveValue("0");
    expect(fields.fraction).toHaveValue("5");
  });

  it("leaves an empty whole segment empty when an arrow moves on", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.whole);
    await user.keyboard("{ArrowRight}");
    expect(fields.fraction).toHaveFocus();
    expect(fields.whole).toHaveValue("");
    expect(fields.onChange).not.toHaveBeenCalled();
  });

  it("ignores the grouping key when typed", async () => {
    const user = setupUser();
    const fields = renderEmpty();
    await user.click(fields.whole);
    await user.keyboard("1,2");
    expect(fields.whole).toHaveValue("12");
    expect(fields.whole).toHaveFocus();
  });
});

// ---------------------------------------------------------------------------
// getCurrencyParts
// ---------------------------------------------------------------------------

describe("getCurrencyParts", () => {
  it("reads symbol side and separator from the locale", () => {
    expect(getCurrencyParts("en-US", "USD")).toEqual({
      symbol: "$",
      symbolAfter: false,
      decimal: ".",
      group: ",",
      fractionDigits: 2,
    });
    expect(getCurrencyParts("de-DE", "EUR")).toMatchObject({
      symbol: "€",
      symbolAfter: true,
      decimal: ",",
      group: ".",
    });
  });

  it("falls back to the code for an unknown currency", () => {
    expect(getCurrencyParts("en-US", "NOT-A-CODE").symbol).toBe("NOT-A-CODE");
  });
});
