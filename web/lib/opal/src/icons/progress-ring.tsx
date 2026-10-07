import { IconLoader } from "@opal/loaders/icon-loader/components";
import type { IconProps } from "@opal/types";

export interface SvgProgressRingProps extends IconProps {
  succeeded?: number;
  failed?: number;
  inProgress?: number;
  queued?: number;
}

type ProgressRingState = Exclude<keyof SvgProgressRingProps, keyof IconProps>;

// Clockwise from the top. `null` leaves a gap for the state.
const STATES: ReadonlyArray<[ProgressRingState, string | null]> = [
  ["succeeded", "stroke-status-success-05"],
  ["failed", "stroke-status-error-05"],
  ["inProgress", "stroke-text-01"],
  ["queued", null],
];

const VIEWBOX = 16;
const STROKE_WIDTH = 2;
const RADIUS = (VIEWBOX - STROKE_WIDTH) / 2;
const CIRCUMFERENCE = 2 * Math.PI * RADIUS;
const CENTER = VIEWBOX / 2;

/**
 * A ring split into one arc per state, each the state's share of the total:
 * succeeded (green), failed (red), in progress (grey). Queued items leave a
 * gap.
 *
 * A ring with no arc would look empty. With nothing at all it is full green,
 * and with only queued items it is the spinner.
 */
const SvgProgressRing = ({
  size,
  succeeded = 0,
  failed = 0,
  inProgress = 0,
  queued = 0,
  ...props
}: SvgProgressRingProps) => {
  const counts: Record<ProgressRingState, number> = {
    succeeded,
    failed,
    inProgress,
    queued,
  };
  const total = STATES.reduce(
    (sum, [state]) => sum + Math.max(counts[state], 0),
    0
  );
  const drawn = STATES.filter(
    ([state, className]) => className !== null && counts[state] > 0
  );
  if (total > 0 && drawn.length === 0) {
    return <IconLoader size={size} {...props} />;
  }

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
        {total === 0 ? (
          <circle
            cx={CENTER}
            cy={CENTER}
            r={RADIUS}
            strokeWidth={STROKE_WIDTH}
            className="stroke-status-success-05"
          />
        ) : (
          STATES.map(([state, className]) => {
            const count = Math.max(counts[state], 0);
            const length = (count / total) * CIRCUMFERENCE;
            const start = offset;
            offset += length;
            if (className === null || count === 0) return null;
            return (
              <circle
                key={state}
                cx={CENTER}
                cy={CENTER}
                r={RADIUS}
                strokeWidth={STROKE_WIDTH}
                className={className}
                strokeDasharray={`${length} ${CIRCUMFERENCE - length}`}
                strokeDashoffset={-start}
              />
            );
          })
        )}
      </g>
    </svg>
  );
};

export default SvgProgressRing;
