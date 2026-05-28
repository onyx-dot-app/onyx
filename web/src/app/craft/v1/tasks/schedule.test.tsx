import type {
  DailyWeeklyPayload,
  IntervalPayload,
} from "@/app/craft/v1/tasks/interfaces";
import {
  compileLocalPayloadToUtcCron,
  decodeUtcCronToLocalPayload,
  humanReadableScheduleFromCron,
} from "@/app/craft/v1/tasks/schedule";

const REFERENCE_DATE = new Date("2026-05-25T12:00:00.000Z");

describe("scheduled task browser-local schedule helpers", () => {
  it("round-trips daily/weekly schedules through the stored cron", () => {
    const payload: DailyWeeklyPayload = {
      time_of_day: "09:30",
      weekdays: [1, 3, 5],
    };

    const compiled = compileLocalPayloadToUtcCron(
      "daily_weekly",
      payload,
      REFERENCE_DATE
    );

    if (!compiled.ok) throw new Error(compiled.error);

    const decoded = decodeUtcCronToLocalPayload(
      "daily_weekly",
      compiled.cron,
      REFERENCE_DATE
    );
    expect(decoded).toEqual({ mode: "daily_weekly", payload });
    expect(
      humanReadableScheduleFromCron(
        "daily_weekly",
        compiled.cron,
        REFERENCE_DATE
      )
    ).toBe("Mon, Wed, Fri at 9:30 AM");
  });

  it("shifts every weekday uniformly when the local time crosses UTC midnight", () => {
    // 23:00 local (PDT, UTC-7) lands at 06:00 UTC the *next* day, so every
    // selected weekday must advance by one. The old code converted each
    // weekday's next occurrence independently and collapsed the time to the
    // first weekday, which could diverge by an hour across DST boundaries.
    const payload: DailyWeeklyPayload = {
      time_of_day: "23:00",
      weekdays: [1, 3, 5],
    };

    const compiled = compileLocalPayloadToUtcCron(
      "daily_weekly",
      payload,
      REFERENCE_DATE
    );
    if (!compiled.ok) throw new Error(compiled.error);

    // 06:00 UTC, weekdays uniformly shifted +1 → Tue, Thu, Sat.
    expect(compiled.cron).toBe("0 6 * * 2,4,6");

    const decoded = decodeUtcCronToLocalPayload(
      "daily_weekly",
      compiled.cron,
      REFERENCE_DATE
    );
    expect(decoded).toEqual({ mode: "daily_weekly", payload });
  });

  it("round-trips day interval schedules through the stored cron", () => {
    const payload: IntervalPayload = {
      unit: "days",
      every: 2,
      time_of_day: "23:15",
    };

    const compiled = compileLocalPayloadToUtcCron(
      "interval",
      payload,
      REFERENCE_DATE
    );

    if (!compiled.ok) throw new Error(compiled.error);

    const decoded = decodeUtcCronToLocalPayload(
      "interval",
      compiled.cron,
      REFERENCE_DATE
    );
    expect(decoded).toEqual({ mode: "interval", payload });
  });
});
