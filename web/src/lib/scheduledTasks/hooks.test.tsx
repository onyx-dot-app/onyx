import type { ReactNode } from "react";
import { NextIntlClientProvider } from "next-intl";
import { renderHook } from "@testing-library/react";
import englishMessages from "@/i18n/messages/en.json";
import { compileLocalPayloadToUtcCron } from "@/app/craft/v1/tasks/schedule";
import { useScheduledTaskFormat } from "@/lib/scheduledTasks/hooks";

const LOCAL_ZONE = Intl.DateTimeFormat().resolvedOptions().timeZone;
// next-intl formats in the server's zone. Any zone far from the local one shows a missing override.
const SERVER_ZONE =
  LOCAL_ZONE === "Pacific/Kiritimati" ? "Etc/GMT+12" : "Pacific/Kiritimati";

function wrapper({ children }: { children: ReactNode }) {
  return (
    <NextIntlClientProvider
      locale="en"
      messages={englishMessages}
      timeZone={SERVER_ZONE}
    >
      {children}
    </NextIntlClientProvider>
  );
}

describe("useScheduledTaskFormat", () => {
  const nextRun = new Date(2026, 10, 23, 9, 0);

  it("shows a weekly schedule at the browser's local time and weekday", () => {
    const compiled = compileLocalPayloadToUtcCron(
      "daily_weekly",
      { time_of_day: "09:00", weekdays: [1] },
      nextRun
    );
    if (!compiled.ok) throw new Error(compiled.error);
    const { result } = renderHook(() => useScheduledTaskFormat(), { wrapper });

    const text = result.current.schedule(
      "daily_weekly",
      compiled.cron,
      nextRun.toISOString()
    );

    expect(text).toContain("9:00");
    expect(text).toContain("Mon");
  });

  it("shows an absolute time in the browser's zone", () => {
    const { result } = renderHook(() => useScheduledTaskFormat(), { wrapper });

    expect(result.current.absolute(nextRun.toISOString())).toContain("9:00");
  });
});
