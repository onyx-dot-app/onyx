import type { IconProps } from "@opal/types";

export interface SvgProgressRingProps extends IconProps {
  /**
   * Every item the ring stands for; the part not succeeded, failed or in
   * progress is queued. Defaults to the sum of the other three, and is never
   * taken as less than it.
   */
  total?: number;
  succeeded?: number;
  failed?: number;
  inProgress?: number;
}

const VIEWBOX = 16;
const STROKE_WIDTH = 2;
const RADIUS = (VIEWBOX - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const CENTER = VIEWBOX / 2;

/**
 * A ring split into arcs, clockwise from the top in the order succeeded
 * (green), failed (red), in progress (grey). Queued items show as the faint
 * track, so a ring with nothing started, or nothing at all, is a full track.
 * The in-progress arc pulses.
 */
const SvgProgressRing = ({
  size,
  total,
  succeeded = 0,
  failed = 0,
  inProgress = 0,
  ...props
}: SvgProgressRingProps) => {
  const segments: Array<[number, string]> = [
    [succeeded, "stroke-status-success-05"],
    [failed, "stroke-status-error-05"],
    // The pulse tells running apart from the queued track.
    [inProgress, "stroke-text-01 motion-safe:animate-pulse"],
  ];
  const sum = succeeded + failed + inProgress;
  const ringTotal = Math.max(total ?? sum, sum);
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
      <circle
        cx={CENTER}
        cy={CENTER}
        r={RADIUS}
        strokeWidth={STROKE_WIDTH}
        className="stroke-border-01"
      />
      <g transform={`rotate(-90 ${CENTER} ${CENTER})`}>
        {segments.map(([count, className]) => {
          if (count <= 0 || ringTotal === 0) return null;
          const length = (count / ringTotal) * CIRCUMFERENCE;
          const arc = (
            <circle
              key={className}
              cx={CENTER}
              cy={CENTER}
              r={RADIUS}
              strokeWidth={STROKE_WIDTH}
              className={className}
              strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
              strokeDashoffset={-offset}
            />
          );
          offset += length;
          return arc;
        })}
      </g>
    </svg>
  );
};

export default SvgProgressRing;
