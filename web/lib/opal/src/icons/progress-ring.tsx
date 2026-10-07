import type { IconProps } from "@opal/types";

/**
 * Each count takes its share of the ring, out of the sum of all five. The
 * caller decides what each colour means.
 */
export interface SvgProgressRingProps extends IconProps {
  success?: number;
  error?: number;
  warning?: number;
  neutral?: number;
  /** Counted in the total, but drawn as a gap. */
  rest?: number;
}

type ProgressRingPart = Exclude<keyof SvgProgressRingProps, keyof IconProps>;

// Clockwise from the top. `null` leaves a gap.
const PARTS: ReadonlyArray<[ProgressRingPart, string | null]> = [
  ["success", "stroke-status-success-05"],
  ["error", "stroke-status-error-05"],
  ["warning", "stroke-status-warning-05"],
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
 * neutral, then a gap for the rest. With every count at 0 it draws nothing.
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
          const length =
            total === 0 ? 0 : (counts[part] / total) * CIRCUMFERENCE;
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
