import { IconLoader } from "@opal/loaders/icon-loader/components";
import type { IconProps } from "@opal/types";

/**
 * Each count takes its share of the ring, out of the sum of all five. The
 * caller decides what each colour means; negative counts read as 0.
 */
export interface SvgProgressRingProps extends IconProps {
  /** Green arc, e.g. items that succeeded. */
  success?: number;
  /** Red arc, e.g. items that failed. */
  error?: number;
  /** Amber arc, e.g. items that need attention. */
  warning?: number;
  /** Light grey arc, e.g. items in progress. */
  neutral?: number;
  /** A gap, e.g. items not started. Counted in the total, but not drawn. */
  rest?: number;
}

type ProgressRingPart = Exclude<keyof SvgProgressRingProps, keyof IconProps>;

// Clockwise from the top. `null` leaves a gap.
const PARTS: ReadonlyArray<[ProgressRingPart, string | null]> = [
  ["success", "stroke-status-success-05"],
  ["error", "stroke-status-error-05"],
  ["warning", "stroke-theme-amber-05"],
  ["neutral", "stroke-text-01"],
  ["rest", null],
];

const VIEWBOX = 16;
const STROKE_WIDTH = 2;
const RADIUS = (VIEWBOX - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const CENTER = VIEWBOX / 2;

/**
 * A ring of coloured arcs, clockwise from the top: success, error, warning,
 * neutral, then a gap for the rest.
 *
 * With no coloured arc the ring would be empty, so it shows the spinner when
 * only `rest` is left, and a full success ring when every count is 0.
 */
const SvgProgressRing = ({
  size,
  success = 0,
  error = 0,
  warning = 0,
  neutral = 0,
  rest = 0,
  ...props
}: SvgProgressRingProps) => {
  const counts: Record<ProgressRingPart, number> = {
    success: Math.max(success, 0),
    error: Math.max(error, 0),
    warning: Math.max(warning, 0),
    neutral: Math.max(neutral, 0),
    rest: Math.max(rest, 0),
  };
  const total = PARTS.reduce((sum, [part]) => sum + counts[part], 0);
  if (total === counts.rest && counts.rest > 0) {
    return <IconLoader size={size} {...props} />;
  }
  if (total === 0) counts.success = 1;
  const drawnTotal = Math.max(total, 1);
  let offset = 0;

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      {...props}
    >
      <g transform={`rotate(-90 ${CENTER} ${CENTER})`}>
        {PARTS.map(([part, className]) => {
          const length = (counts[part] / drawnTotal) * CIRCUMFERENCE;
          const start = offset;
          offset += length;
          if (className === null || length === 0) return null;
          return (
            <circle
              key={part}
              cx={CENTER}
              cy={CENTER}
              r={RADIUS}
              strokeWidth={STROKE_WIDTH}
              className={className}
              strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
              strokeDashoffset={-start}
            />
          );
        })}
      </g>
    </svg>
  );
};

export default SvgProgressRing;
