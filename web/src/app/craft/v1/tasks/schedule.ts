/**
 * Pure helpers for the schedule editor.
 *
 * - ``compileToCron``: normalize the three editor modes into a single 5-field
 *   cron expression (mirrors ``backend/.../scheduled_tasks/schedule.py``).
 * - ``computeNextRuns``: best-effort client-side preview of the next N fires,
 *   used by the editor's "next 3 runs" panel before save.
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

/**
 * Simple cron field parser supporting:
 *  - ``*``
 *  - integer literals (``5``)
 *  - comma lists (``1,3,5``)
 *  - step values from ``*`` (``*\/15``)
 *  - step values from a literal (``5/15``) — uncommon but legal
 *
 * Range expressions (``1-5``) are *not* supported here — they'd require a
 * lot more code, and the simple cases above cover every cron our editor
 * compiles. Advanced-mode users get to test against the server-computed
 * preview after save.
 */
function expandField(field: string, min: number, max: number): number[] | null {
  if (field === "*") {
    const out: number[] = [];
    for (let i = min; i <= max; i++) out.push(i);
    return out;
  }
  // step expression
  if (field.includes("/")) {
    const parts = field.split("/");
    const base = parts[0] ?? "";
    const stepStr = parts[1] ?? "";
    const step = Number(stepStr);
    if (!Number.isFinite(step) || step <= 0) return null;
    let start = min;
    if (base !== "*" && base !== "") {
      const n = Number(base);
      if (!Number.isFinite(n)) return null;
      start = n;
    }
    const out: number[] = [];
    for (let i = start; i <= max; i += step) out.push(i);
    return out;
  }
  if (field.includes(",")) {
    const parts = field.split(",").map((p) => Number(p.trim()));
    if (parts.some((n) => !Number.isFinite(n) || n < min || n > max)) {
      return null;
    }
    return Array.from(new Set(parts)).sort((a, b) => a - b);
  }
  const n = Number(field);
  if (!Number.isFinite(n) || n < min || n > max) return null;
  return [n];
}

/**
 * Compute the next ``count`` fires of ``cron`` in the given IANA timezone,
 * starting strictly after ``after`` (default: now). Returns ISO strings in
 * UTC.
 *
 * Returns an empty array if the cron expression cannot be parsed by our
 * tiny client-side parser.
 *
 * Notes / caveats:
 *  - Day-of-month (``dom``) and day-of-week (``dow``) follow cron semantics:
 *    when both are restricted (neither is ``*``), a fire happens on any day
 *    matching *either* constraint. When one is ``*``, only the other is
 *    enforced.
 *  - Months follow 1-12 indexing.
 *  - Timezone handling uses ``Intl.DateTimeFormat`` to map a UTC instant
 *    into local components in the target zone.
 */
export function computeNextRuns(
  cron: string,
  timezone: string,
  count: number,
  after: Date = new Date()
): string[] {
  const fields = cron.trim().split(/\s+/);
  if (fields.length !== 5) return [];
  const [minuteF, hourF, domF, monthF, dowF] = fields as [
    string,
    string,
    string,
    string,
    string,
  ];

  const minutes = expandField(minuteF, 0, 59);
  const hours = expandField(hourF, 0, 23);
  const dom = expandField(domF, 1, 31);
  const months = expandField(monthF, 1, 12);
  const dow = expandField(dowF, 0, 6);

  if (!minutes || !hours || !dom || !months || !dow) return [];

  const domRestricted = domF !== "*";
  const dowRestricted = dowF !== "*";

  // Iterate UTC minutes; for each candidate, derive the local components in
  // the target timezone and test the cron fields against those.
  const startUtc = new Date(after.getTime());
  // round up to the next whole minute so we never re-fire on the current
  // second.
  startUtc.setUTCSeconds(0, 0);
  startUtc.setUTCMinutes(startUtc.getUTCMinutes() + 1);

  const SAFETY_LIMIT_MINUTES = 60 * 24 * 366 * 2; // ~2 years

  const fmt = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    weekday: "short",
  });

  const weekdayMap: Record<string, number> = {
    Sun: 0,
    Mon: 1,
    Tue: 2,
    Wed: 3,
    Thu: 4,
    Fri: 5,
    Sat: 6,
  };

  const minutesSet = new Set(minutes);
  const hoursSet = new Set(hours);
  const domSet = new Set(dom);
  const monthsSet = new Set(months);
  const dowSet = new Set(dow);

  const results: string[] = [];
  const cursor = new Date(startUtc.getTime());

  for (let i = 0; i < SAFETY_LIMIT_MINUTES && results.length < count; i++) {
    const parts = fmt.formatToParts(cursor);
    const get = (type: string): string =>
      parts.find((p) => p.type === type)?.value ?? "";

    const minute = Number(get("minute"));
    const hour = Number(get("hour"));
    const day = Number(get("day"));
    const month = Number(get("month"));
    const weekdayValue = weekdayMap[get("weekday")];
    if (weekdayValue === undefined) {
      // Unknown weekday from the Intl formatter — skip this candidate.
      cursor.setUTCMinutes(cursor.getUTCMinutes() + 1);
      continue;
    }

    let dayOk: boolean;
    if (domRestricted && dowRestricted) {
      dayOk = domSet.has(day) || dowSet.has(weekdayValue);
    } else if (domRestricted) {
      dayOk = domSet.has(day);
    } else if (dowRestricted) {
      dayOk = dowSet.has(weekdayValue);
    } else {
      dayOk = true;
    }

    if (
      minutesSet.has(minute) &&
      hoursSet.has(hour) &&
      monthsSet.has(month) &&
      dayOk
    ) {
      results.push(cursor.toISOString());
    }

    cursor.setUTCMinutes(cursor.getUTCMinutes() + 1);
  }

  return results;
}

// ---------------------------------------------------------------------------
// Cron → editor payload (best-effort reconstruction for the edit page)
// ---------------------------------------------------------------------------

/**
 * Reconstruct a UI-friendly payload from a stored cron expression and the
 * editor_mode hint. The backend stores cron + editor_mode but does not
 * round-trip editor_payload, so we re-derive it on the edit page.
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
