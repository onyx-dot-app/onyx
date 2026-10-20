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

  it("steps to the fraction on Enter, then submits the form", async () => {
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
    expect(screen.getByLabelText("Fractional amount")).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();

    await user.keyboard("5{Enter}");
    expect(onSubmit).toHaveBeenCalledTimes(1);
  });

  it("trims leading zeros as soon as focus leaves the whole segment", async () => {
    const user = setupUser();
    render(<InputCurrency value={null} onChange={() => {}} />);

    await user.click(screen.getByLabelText("Whole amount"));
    await user.keyboard("0000{Enter}");
    expect(screen.getByLabelText("Fractional amount")).toHaveFocus();
    expect(screen.getByLabelText("Whole amount")).toHaveValue("0");
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
// getCurrencyParts
// ---------------------------------------------------------------------------

describe("getCurrencyParts", () => {
  it("reads symbol side and separator from the locale", () => {
    expect(getCurrencyParts("en-US", "USD")).toEqual({
      symbol: "$",
      symbolAfter: false,
      decimal: ".",
      fractionDigits: 2,
    });
    expect(getCurrencyParts("de-DE", "EUR")).toMatchObject({
      symbol: "€",
      symbolAfter: true,
      decimal: ",",
    });
  });

  it("falls back to the code for an unknown currency", () => {
    expect(getCurrencyParts("en-US", "NOT-A-CODE").symbol).toBe("NOT-A-CODE");
  });
});
