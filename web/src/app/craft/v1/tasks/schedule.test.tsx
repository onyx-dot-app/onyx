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

  it("converts daily/weekly schedules via a single shared day-shift", () => {
    // A late-evening local time can roll into the next UTC day. The whole
    // schedule must shift by ONE shared day-delta (derived from a single
    // instant) rather than converting each weekday independently — otherwise
    // weekdays could diverge across a DST boundary. We derive the expected
    // cron from the host's own timezone instead of hard-coding a zone-specific
    // string, so the assertion holds under any TZ (CI runs in UTC; dev
    // machines often don't).
    const payload: DailyWeeklyPayload = {
      time_of_day: "23:00",
      weekdays: [1, 3, 5],
    };

    // Independent reference conversion: one instant in, one day-shift out.
    const instant = new Date(REFERENCE_DATE.getTime());
    instant.setHours(23, 0, 0, 0);
    const localMidnight = Date.UTC(
      instant.getFullYear(),
      instant.getMonth(),
      instant.getDate()
    );
    const utcMidnight = Date.UTC(
      instant.getUTCFullYear(),
      instant.getUTCMonth(),
      instant.getUTCDate()
    );
    const dayDelta = Math.round((utcMidnight - localMidnight) / 86_400_000);
    const expectedWeekdays = payload.weekdays
      .map((weekday) => (((weekday + dayDelta) % 7) + 7) % 7)
      .sort((a, b) => a - b);
    const expectedCron = `${instant.getUTCMinutes()} ${instant.getUTCHours()} * * ${expectedWeekdays.join(",")}`;

    const compiled = compileLocalPayloadToUtcCron(
      "daily_weekly",
      payload,
      REFERENCE_DATE
    );
    if (!compiled.ok) throw new Error(compiled.error);

    // One shared time + a uniform weekday shift, with no weekdays dropped.
    expect(compiled.cron).toBe(expectedCron);
    expect(expectedWeekdays).toHaveLength(payload.weekdays.length);

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
