import { act, render, screen } from "@tests/setup/test-utils";
import { ErrorBanner } from "@/app/app/message/Resubmit";
import { RATE_LIMITED_ERROR_CODE } from "@/app/app/interfaces";

describe("rate-limit error banner", () => {
  beforeEach(() => {
    jest.useFakeTimers();
    jest.setSystemTime(new Date("2026-07-28T12:00:00Z"));
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test("updates when the reset time is reached", () => {
    render(
      <ErrorBanner
        error="You've reached the usage budget for your account."
        errorCode={RATE_LIMITED_ERROR_CODE}
        details={{ reset_at: "2026-07-28T12:00:30Z" }}
      />
    );

    expect(screen.getByText(/Resets in 1 minute/)).toBeInTheDocument();

    act(() => {
      jest.advanceTimersByTime(30_000);
    });

    expect(screen.getByText("You can try again now.")).toBeInTheDocument();
  });
});
