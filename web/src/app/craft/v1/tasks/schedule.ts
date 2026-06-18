/**
 * Pure helpers for the schedule editor.
 *
 * - ``compileToCron``: normalize the three editor modes into a single 5-field
 *   cron expression (mirrors ``backend/.../scheduled_tasks/schedule.py``).
 * - ``compileLocalPayloadToUtcCron``: compile browser-local editor state into
 *   the UTC cron persisted by the backend.
 * - ``humanReadableSchedule``: lightweight summary fallback when we can only
 *   render client-side.
 *
 * Weekday convention: 0=Sunday .. 6=Saturday (cron / backend).
 */

import type {
  AdvancedPayload,
  DailyWeeklyPayload,
  EditorMode,
  EditorPayload,
  IntervalPayload,
  IntervalUnit,
} from "@/app/craft/v1/tasks/interfaces";

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

export interface ScheduleValidationOk {
  ok: true;
  cron: string;
}

export interface ScheduleValidationErr {
  ok: false;
  error: string;
}

export type ScheduleValidation = ScheduleValidationOk | ScheduleValidationErr;

const TIME_RE = /^([01]?\d|2[0-3]):([0-5]\d)$/;

function parseTimeOfDay(value: string | null | undefined): {
  hour: number;
  minute: number;
} | null {
  if (!value) return null;
  const m = TIME_RE.exec(value);
  if (!m) return null;
  return { hour: Number(m[1]), minute: Number(m[2]) };
}

function timeOfDay(hour: number, minute: number): string {
  return `${pad2(hour)}:${pad2(minute)}`;
}

function localTimeOfDayToUtc(
  value: string | null | undefined,
  referenceDate: Date
): { hour: number; minute: number } | null {
  const time = parseTimeOfDay(value);
  if (!time) return null;
  const date = new Date(referenceDate.getTime());
  date.setHours(time.hour, time.minute, 0, 0);
  return { hour: date.getUTCHours(), minute: date.getUTCMinutes() };
}

function utcTimeOfDayToLocal(
  value: string | null | undefined,
  referenceDate: Date
): { hour: number; minute: number } | null {
  const time = parseTimeOfDay(value);
  if (!time) return null;
  const date = new Date(referenceDate.getTime());
  date.setUTCHours(time.hour, time.minute, 0, 0);
  return { hour: date.getHours(), minute: date.getMinutes() };
}

function uniqueSortedWeekdays(weekdays: number[]): number[] {
  return Array.from(new Set(weekdays)).sort((a, b) => a - b);
}

/**
 * For a given absolute instant, how many calendar days its UTC date sits ahead
 * of its local date (-1, 0, or +1). When a wall-clock time converts across
 * midnight, the weekday shifts with it; this lets us apply that one shift
 * uniformly across a daily/weekly schedule's weekday set.
 */
function utcMinusLocalDayDelta(instant: Date): number {
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
  return Math.round((utcMidnight - localMidnight) / 86_400_000);
}

function shiftWeekday(weekday: number, dayDelta: number): number {
  return (((weekday + dayDelta) % 7) + 7) % 7;
}

export function localPayloadToUtcPayload(
  mode: EditorMode,
  payload: EditorPayload,
  referenceDate: Date = new Date()
): EditorPayload {
  if (mode === "interval") {
    const intervalPayload = payload as IntervalPayload;
    if (intervalPayload.unit !== "days") return intervalPayload;
    const utcTime = localTimeOfDayToUtc(
      intervalPayload.time_of_day,
      referenceDate
    );
    if (!utcTime) return intervalPayload;
    return {
      ...intervalPayload,
      time_of_day: timeOfDay(utcTime.hour, utcTime.minute),
    };
  }

  if (mode === "daily_weekly") {
    const dailyWeeklyPayload = payload as DailyWeeklyPayload;
    const localTime = parseTimeOfDay(dailyWeeklyPayload.time_of_day);
    if (!localTime) return dailyWeeklyPayload;

    // Convert the wall-clock time once on the reference date. A single
    // `M H * * d1,d2,...` cron carries only one (hour, minute) and one
    // day-shift, so we derive both from one instant and apply the same shift
    // to every selected weekday. Converting each weekday's next occurrence
    // independently would diverge across a DST boundary.
    const instant = new Date(referenceDate.getTime());
    instant.setHours(localTime.hour, localTime.minute, 0, 0);
    const dayDelta = utcMinusLocalDayDelta(instant);

    const weekdays = Array.isArray(dailyWeeklyPayload.weekdays)
      ? dailyWeeklyPayload.weekdays
      : [];
    return {
      ...dailyWeeklyPayload,
      time_of_day: timeOfDay(instant.getUTCHours(), instant.getUTCMinutes()),
      weekdays: uniqueSortedWeekdays(
        weekdays.map((weekday) => shiftWeekday(weekday, dayDelta))
      ),
    };
  }

  return payload;
}

function utcPayloadToLocalPayload(
  mode: EditorMode,
  payload: EditorPayload,
  referenceDate: Date
): EditorPayload {
  if (mode === "interval") {
    const intervalPayload = payload as IntervalPayload;
    if (intervalPayload.unit !== "days") return intervalPayload;
    const localTime = utcTimeOfDayToLocal(
      intervalPayload.time_of_day,
      referenceDate
    );
    if (!localTime) return intervalPayload;
    return {
      ...intervalPayload,
      time_of_day: timeOfDay(localTime.hour, localTime.minute),
    };
  }

  if (mode === "daily_weekly") {
    const dailyWeeklyPayload = payload as DailyWeeklyPayload;
    const utcTime = parseTimeOfDay(dailyWeeklyPayload.time_of_day);
    if (!utcTime) return dailyWeeklyPayload;

    // Mirror of the encode path: convert the stored UTC wall-clock once and
    // apply the resulting day-shift uniformly to every weekday. See
    // `localPayloadToUtcPayload`.
    const instant = new Date(referenceDate.getTime());
    instant.setUTCHours(utcTime.hour, utcTime.minute, 0, 0);
    const dayDelta = utcMinusLocalDayDelta(instant);

    const weekdays = Array.isArray(dailyWeeklyPayload.weekdays)
      ? dailyWeeklyPayload.weekdays
      : [];
    return {
      ...dailyWeeklyPayload,
      time_of_day: timeOfDay(instant.getHours(), instant.getMinutes()),
      weekdays: uniqueSortedWeekdays(
        weekdays.map((weekday) => shiftWeekday(weekday, -dayDelta))
      ),
    };
  }

  return payload;
}

// ---------------------------------------------------------------------------
// Cron compilation
// ---------------------------------------------------------------------------

export function compileToCron(
  mode: EditorMode,
  payload: EditorPayload
): ScheduleValidation {
  switch (mode) {
    case "interval":
      return compileInterval(payload as IntervalPayload);
    case "daily_weekly":
      return compileDailyWeekly(payload as DailyWeeklyPayload);
    case "advanced":
      return compileAdvanced(payload as AdvancedPayload);
  }
}

export function compileLocalPayloadToUtcCron(
  mode: EditorMode,
  payload: EditorPayload,
  referenceDate: Date = new Date()
): ScheduleValidation {
  return compileToCron(
    mode,
    localPayloadToUtcPayload(mode, payload, referenceDate)
  );
}

function compileInterval(payload: IntervalPayload): ScheduleValidation {
  const every = Number(payload?.every);
  if (!Number.isFinite(every) || every < 1) {
    return { ok: false, error: "Interval must be at least 1." };
  }
  const unit: IntervalUnit = payload.unit;

  if (unit === "minutes") {
    if (every > 59) {
      return { ok: false, error: "Use hours/days for intervals over 59 min." };
    }
    return { ok: true, cron: `*/${every} * * * *` };
  }
  if (unit === "hours") {
    if (every > 23) {
      return { ok: false, error: "Use days for intervals over 23 hours." };
    }
    return { ok: true, cron: `0 */${every} * * *` };
  }
  // days — requires time_of_day
  const time = parseTimeOfDay(payload.time_of_day);
  if (!time) {
    return {
      ok: false,
      error: "Pick a time of day for day-cadence intervals.",
    };
  }
  return { ok: true, cron: `${time.minute} ${time.hour} */${every} * *` };
}

function compileDailyWeekly(payload: DailyWeeklyPayload): ScheduleValidation {
  const time = parseTimeOfDay(payload?.time_of_day);
  if (!time) {
    return { ok: false, error: "Pick a time of day." };
  }
  const weekdays = Array.isArray(payload?.weekdays) ? payload.weekdays : [];
  for (const d of weekdays) {
    if (!Number.isInteger(d) || d < 0 || d > 6) {
      return { ok: false, error: "Weekday values must be 0-6 (Sun..Sat)." };
    }
  }
  const dayField =
    weekdays.length === 0
      ? "*"
      : Array.from(new Set(weekdays))
          .sort((a, b) => a - b)
          .join(",");
  return {
    ok: true,
    cron: `${time.minute} ${time.hour} * * ${dayField}`,
  };
}

function compileAdvanced(payload: AdvancedPayload): ScheduleValidation {
  const expr = (payload?.cron ?? "").trim();
  if (!expr) return { ok: false, error: "Enter a cron expression." };
  const fields = expr.split(/\s+/);
  if (fields.length !== 5) {
    return {
      ok: false,
      error: "Cron must have exactly 5 fields (minute hour day month weekday).",
    };
  }
  return { ok: true, cron: expr };
}

// ---------------------------------------------------------------------------
// Next-fires preview (client-side, best-effort).
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// Cron → editor payload (best-effort reconstruction for the edit page)
// ---------------------------------------------------------------------------

/**
 * Reconstruct the stored payload shape from a stored cron expression and the
 * editor_mode hint. Use ``decodeUtcCronToLocalPayload`` for browser display.
 *
 * If we can't confidently decode the cron back into the chosen mode, we fall
 * back to ``advanced`` mode so the user sees the raw expression.
 */
export function decodeCronToPayload(
  mode: EditorMode,
  cron: string
): { mode: EditorMode; payload: EditorPayload } {
  const fields = cron.trim().split(/\s+/);
  if (fields.length !== 5) {
    return { mode: "advanced", payload: { cron } };
  }
  const [minuteF, hourF, domF, monthF, dowF] = fields as [
    string,
    string,
    string,
    string,
    string,
  ];

  if (mode === "interval") {
    // */N * * * *  →  N minutes
    const minStep = parseStepStar(minuteF);
    if (
      minStep !== null &&
      hourF === "*" &&
      domF === "*" &&
      monthF === "*" &&
      dowF === "*"
    ) {
      return { mode: "interval", payload: { unit: "minutes", every: minStep } };
    }
    // 0 */N * * *  →  N hours
    const hourStep = parseStepStar(hourF);
    if (
      minuteF === "0" &&
      hourStep !== null &&
      domF === "*" &&
      monthF === "*" &&
      dowF === "*"
    ) {
      return { mode: "interval", payload: { unit: "hours", every: hourStep } };
    }
    // M H */N * *  →  N days at H:M
    const domStep = parseStepStar(domF);
    const m = Number(minuteF);
    const h = Number(hourF);
    if (
      domStep !== null &&
      Number.isInteger(m) &&
      Number.isInteger(h) &&
      monthF === "*" &&
      dowF === "*"
    ) {
      return {
        mode: "interval",
        payload: {
          unit: "days",
          every: domStep,
          time_of_day: `${pad2(h)}:${pad2(m)}`,
        },
      };
    }
    // Couldn't decode — fall back.
    return { mode: "advanced", payload: { cron } };
  }

  if (mode === "daily_weekly") {
    // M H * * <dow>
    const m = Number(minuteF);
    const h = Number(hourF);
    if (
      Number.isInteger(m) &&
      Number.isInteger(h) &&
      domF === "*" &&
      monthF === "*"
    ) {
      let weekdays: number[];
      if (dowF === "*") weekdays = [];
      else {
        const parts = dowF.split(",").map((p) => Number(p.trim()));
        if (parts.some((n) => !Number.isInteger(n) || n < 0 || n > 6)) {
          return { mode: "advanced", payload: { cron } };
        }
        weekdays = parts;
      }
      return {
        mode: "daily_weekly",
        payload: {
          time_of_day: `${pad2(h)}:${pad2(m)}`,
          weekdays,
        },
      };
    }
    return { mode: "advanced", payload: { cron } };
  }

  return { mode: "advanced", payload: { cron } };
}

export function decodeUtcCronToLocalPayload(
  mode: EditorMode,
  cron: string,
  referenceDate: Date = new Date()
): { mode: EditorMode; payload: EditorPayload } {
  const decoded = decodeCronToPayload(mode, cron);
  return {
    mode: decoded.mode,
    payload: utcPayloadToLocalPayload(
      decoded.mode,
      decoded.payload,
      referenceDate
    ),
  };
}

function parseStepStar(field: string): number | null {
  if (!field.startsWith("*/")) return null;
  const n = Number(field.slice(2));
  return Number.isInteger(n) && n > 0 ? n : null;
}

function pad2(n: number): string {
  return String(n).padStart(2, "0");
}

// ---------------------------------------------------------------------------
// Human-readable summary (best-effort client-side)
// ---------------------------------------------------------------------------

const WEEKDAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function formatTimeOfDay(hour: number, minute: number): string {
  const period = hour >= 12 ? "PM" : "AM";
  const displayHour = hour % 12 === 0 ? 12 : hour % 12;
  return `${displayHour}:${String(minute).padStart(2, "0")} ${period}`;
}

export function humanReadableSchedule(
  mode: EditorMode,
  payload: EditorPayload | null,
  cron: string | null
): string {
  if (mode === "interval" && payload) {
    const p = payload as IntervalPayload;
    const every = p.every;
    if (!Number.isFinite(every) || every < 1) return "Invalid interval";
    if (p.unit === "minutes")
      return `Every ${every} minute${every === 1 ? "" : "s"}`;
    if (p.unit === "hours")
      return `Every ${every} hour${every === 1 ? "" : "s"}`;
    const t = parseTimeOfDay(p.time_of_day);
    const tStr = t ? ` at ${formatTimeOfDay(t.hour, t.minute)}` : "";
    return `Every ${every} day${every === 1 ? "" : "s"}${tStr}`;
  }
  if (mode === "daily_weekly" && payload) {
    const p = payload as DailyWeeklyPayload;
    const t = parseTimeOfDay(p.time_of_day);
    const tStr = t ? formatTimeOfDay(t.hour, t.minute) : "—";
    if (!p.weekdays || p.weekdays.length === 0) return `Every day at ${tStr}`;
    if (p.weekdays.length === 7) return `Every day at ${tStr}`;
    const labels = Array.from(new Set(p.weekdays))
      .sort((a, b) => a - b)
      .map((d) => WEEKDAY_LABELS[d])
      .join(", ");
    return `${labels} at ${tStr}`;
  }
  if (mode === "advanced" && cron) {
    return `cron: ${cron}`;
  }
  return "—";
}

export function humanReadableScheduleFromCron(
  mode: EditorMode,
  cron: string,
  referenceDate: Date = new Date()
): string {
  const decoded = decodeUtcCronToLocalPayload(mode, cron, referenceDate);
  return humanReadableSchedule(decoded.mode, decoded.payload, cron);
}
