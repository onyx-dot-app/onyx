"use client";

import "@opal/components/inputs/shared.css";
import React from "react";
import type { InputVariants } from "@opal/types";
import { Button, Text } from "@opal/components";
import { SvgX } from "@opal/icons";

// ---------------------------------------------------------------------------
// Types and segment helpers
// ---------------------------------------------------------------------------

interface TimeValue {
  hours: number;
  minutes: number;
  seconds: number;
}

interface TimeSegments {
  hours: string;
  minutes: string;
  seconds: string;
}

const EMPTY_SEGMENTS: TimeSegments = { hours: "", minutes: "", seconds: "" };

const SEGMENT_LIMITS: Record<keyof TimeSegments, number> = {
  hours: 23,
  minutes: 59,
  seconds: 59,
};

const SEGMENT_META: Record<
  keyof TimeSegments,
  { label: string; placeholder: string }
> = {
  hours: { label: "Hours", placeholder: "HH" },
  minutes: { label: "Minutes", placeholder: "MM" },
  seconds: { label: "Seconds", placeholder: "SS" },
};

function toSegments(time: TimeValue | null): TimeSegments {
  if (!time) return EMPTY_SEGMENTS;
  return {
    hours: String(time.hours).padStart(2, "0"),
    minutes: String(time.minutes).padStart(2, "0"),
    seconds: String(time.seconds).padStart(2, "0"),
  };
}

function parseSegments(
  segments: TimeSegments,
  showSeconds: boolean
): TimeValue | null {
  const { hours, minutes } = segments;
  // Hidden seconds parse as zero so HH:MM commits still produce a value.
  const seconds = showSeconds ? segments.seconds : "00";
  if (!hours || !minutes || !seconds) return null;
  const time = {
    hours: Number(hours),
    minutes: Number(minutes),
    seconds: Number(seconds),
  };
  const valid = (Object.keys(SEGMENT_LIMITS) as (keyof TimeSegments)[]).every(
    (part) => time[part] >= 0 && time[part] <= SEGMENT_LIMITS[part]
  );
  return valid ? time : null;
}

// Equality at the editable granularity: with seconds hidden they are not
// compared, so an editless tab-through never fires a zeroing onChange.
function sameCommitted(
  a: TimeValue,
  b: TimeValue,
  showSeconds: boolean
): boolean {
  return (
    a.hours === b.hours &&
    a.minutes === b.minutes &&
    (!showSeconds || a.seconds === b.seconds)
  );
}

// ---------------------------------------------------------------------------
// InputTime
// ---------------------------------------------------------------------------

interface InputTimeProps {
  /** Selected time (24-hour), or null when empty. */
  value: TimeValue | null;

  /** Fires with the committed time, or null when cleared. */
  onChange: (time: TimeValue | null) => void;

  /** Error chrome. */
  error?: boolean;
  disabled?: boolean;

  /** Shows a clear action while a value is set and the field is enabled. */
  clearable?: boolean;

  /**
   * Shows the seconds segment. When hidden, committed values carry zero
   * seconds.
   * @default true
   */
  showSeconds?: boolean;

  /** Applied to the hours segment so a `<label htmlFor>` can target the field. */
  id?: string;
}

/**
 * InputTime (Figma Input/Time): segmented 24-hour HH:MM:SS field on the
 * shared .opal-input chrome. Typing commits on blur or Enter once the
 * segments form a valid time, invalid drafts revert to the committed value.
 */
function InputTime({
  value,
  onChange,
  error,
  disabled,
  clearable,
  showSeconds = true,
  id,
}: InputTimeProps) {
  const variant: InputVariants = disabled
    ? "disabled"
    : error
      ? "error"
      : "primary";

  const [segments, setSegments] = React.useState<TimeSegments>(() =>
    toSegments(value)
  );

  const hoursRef = React.useRef<HTMLInputElement>(null);
  const minutesRef = React.useRef<HTMLInputElement>(null);
  const secondsRef = React.useRef<HTMLInputElement>(null);
  const segmentRefs = {
    hours: hoursRef,
    minutes: minutesRef,
    seconds: secondsRef,
  };

  const segmentParts = showSeconds
    ? (["hours", "minutes", "seconds"] as const)
    : (["hours", "minutes"] as const);

  const valueKey = value
    ? value.hours * 3600 + value.minutes * 60 + value.seconds
    : null;
  React.useEffect(() => {
    setSegments(toSegments(value));
    // Key on the second-of-day, not object identity, so parent re-renders
    // that recreate an equal value don't clobber in-progress typing.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [valueKey]);

  function commit(next: TimeSegments) {
    const parsed = parseSegments(next, showSeconds);
    if (parsed) {
      if (value == null || !sameCommitted(parsed, value, showSeconds)) {
        onChange(parsed);
      } else {
        setSegments(toSegments(value));
      }
    } else {
      setSegments(toSegments(value));
    }
  }

  function handleSegmentChange(
    part: keyof TimeSegments,
    nextRef: React.RefObject<HTMLInputElement | null> | null
  ) {
    return (e: React.ChangeEvent<HTMLInputElement>) => {
      const digits = e.target.value.replace(/\D/g, "").slice(0, 2);
      setSegments((prev) => ({ ...prev, [part]: digits }));
      if (digits.length === 2) nextRef?.current?.focus();
    };
  }

  function handleSegmentKeyDown(
    part: keyof TimeSegments,
    prevRef: React.RefObject<HTMLInputElement | null> | null
  ) {
    return (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        commit(segments);
        return;
      }
      if (e.key === "Backspace" && segments[part] === "") {
        prevRef?.current?.focus();
        e.preventDefault();
      }
    };
  }

  // Commit when focus leaves the whole field, not on intra-field tabbing.
  function handleRootBlur(e: React.FocusEvent<HTMLDivElement>) {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    commit(segments);
  }

  const segmentProps = {
    className: "opal-input-segment",
    type: "text" as const,
    inputMode: "numeric" as const,
    autoComplete: "off",
    disabled,
  };

  const separator = (
    <Text font="main-ui-mono" color="text-02" aria-hidden>
      :
    </Text>
  );

  return (
    <div className="opal-input-segmented-root">
      <div
        className="opal-input opal-input-segmented"
        data-variant={variant}
        role="group"
        aria-label="Time"
        onBlur={handleRootBlur}
      >
        <div className="opal-input-segmented-content">
          {segmentParts.map((part, i) => (
            <React.Fragment key={part}>
              {i > 0 && separator}
              {/* raw-ok: segmented numeric fields have no Opal input primitive. The field chrome is the surrounding .opal-input. */}
              <input
                {...segmentProps}
                ref={segmentRefs[part]}
                id={part === "hours" ? id : undefined}
                aria-label={SEGMENT_META[part].label}
                placeholder={SEGMENT_META[part].placeholder}
                maxLength={2}
                value={segments[part]}
                onChange={handleSegmentChange(
                  part,
                  i < segmentParts.length - 1
                    ? segmentRefs[segmentParts[i + 1]!]
                    : null
                )}
                onKeyDown={handleSegmentKeyDown(
                  part,
                  i > 0 ? segmentRefs[segmentParts[i - 1]!] : null
                )}
              />
            </React.Fragment>
          ))}
        </div>

        {clearable && value && !disabled && (
          <div className="opal-input-segmented-actions">
            <Button
              icon={SvgX}
              prominence="internal"
              size="sm"
              tooltip="Clear"
              onClick={() => onChange(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}

export { InputTime, type InputTimeProps, type TimeValue };
