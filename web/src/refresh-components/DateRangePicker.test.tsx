import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { DateRangePicker } from "@/refresh-components/DateRangePicker";

describe("DateRangePicker", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date(2026, 7, 4, 12));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it("selects and commits a custom range with two date clicks", async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    const onValueChange = jest.fn();

    render(
      <DateRangePicker
        value={{
          from: new Date(2026, 6, 5),
          to: new Date(2026, 7, 4),
        }}
        onValueChange={onValueChange}
      />
    );

    await user.click(screen.getByRole("button", { name: /custom range/i }));
    await user.click(screen.getByRole("button", { name: /august 1st, 2026/i }));

    const endDate = screen.getByRole("button", { name: /august 3rd, 2026/i });
    await user.hover(endDate);

    expect(endDate.parentElement).toHaveClass(
      "opal-calendar-cell--range-preview-end"
    );
    expect(
      screen.getByRole("button", { name: /august 2nd, 2026/i }).parentElement
    ).toHaveClass("opal-calendar-cell--range-preview-middle");

    await user.click(endDate);

    expect(onValueChange).toHaveBeenCalledWith({
      from: new Date(2026, 7, 1),
      to: new Date(2026, 7, 3, 23, 59, 59, 999),
    });
    expect(
      screen.getByRole("button", { name: /custom range/i })
    ).toHaveAttribute("aria-expanded", "false");
  });

  it("emits a full current-day range for 1D", async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });
    const onValueChange = jest.fn();

    render(
      <DateRangePicker
        value={{
          from: new Date(2026, 6, 5),
          to: new Date(2026, 7, 4),
        }}
        onValueChange={onValueChange}
      />
    );

    await user.click(screen.getByRole("button", { name: "1D" }));

    expect(onValueChange).toHaveBeenCalledWith({
      from: new Date(2026, 7, 4),
      to: new Date(2026, 7, 4, 23, 59, 59, 999),
    });
  });

  it("shows the committed custom range when reopened", async () => {
    const user = userEvent.setup({ advanceTimers: jest.advanceTimersByTime });

    render(
      <DateRangePicker
        value={{
          from: new Date(2026, 6, 10),
          to: new Date(2026, 6, 15),
        }}
        onValueChange={jest.fn()}
      />
    );

    await user.click(screen.getByRole("button", { name: /custom range/i }));

    expect(
      screen.getByRole("button", { name: /july 10th, 2026/i }).parentElement
    ).toHaveClass("opal-calendar-cell--range-start");
    expect(
      screen.getByRole("button", { name: /july 15th, 2026/i }).parentElement
    ).toHaveClass("opal-calendar-cell--range-end");
  });
});
