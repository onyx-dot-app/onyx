import { act, render, screen } from "@tests/setup/test-utils";
import { ErrorBanner } from "@/lib/timeline/chat/message/Resubmit";
import { RATE_LIMITED_ERROR_CODE } from "@/app/app/types";

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

  test("a playground limit says so, links to sales and shows no countdown", () => {
    render(
      <ErrorBanner
        error="Your team has used this trial week's allowance."
        errorCode={RATE_LIMITED_ERROR_CODE}
        details={{ policy: "playground", reset_at: "2026-07-31T12:00:00Z" }}
      />
    );

    expect(screen.getByText(/This is a playground limit/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Talk to sales" })).toHaveAttribute(
      "href",
      "https://www.onyx.app/contact-sales"
    );
    expect(screen.queryByText(/Resets in/)).toBeNull();
  });

  test("a cloud limit has no sales link", () => {
    render(
      <ErrorBanner
        error="You've reached the usage budget for your account."
        errorCode={RATE_LIMITED_ERROR_CODE}
        details={{ scope: "user", policy: "cloud_trial" }}
      />
    );

    expect(screen.queryByRole("link")).toBeNull();
  });
});
