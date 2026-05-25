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
