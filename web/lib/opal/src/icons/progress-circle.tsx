import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

export interface SvgProgressCircleProps extends IconProps {
  /** Progress from 0 to 100. 0 is an empty ring, 100 is a green check. */
  value?: number;
}

const RING_RADIUS = 6.667;
// The pie is a thick stroke on a circle at half the pie's radius, so the
// stroke spans from the centre out to the pie's radius.
const PIE_RADIUS = 4.5;
const STROKE_RADIUS = PIE_RADIUS / 2;
const CIRCUMFERENCE = 2 * Math.PI * STROKE_RADIUS;

/**
 * A ring that fills like a pie as `value` rises. The pie animates between
 * values in `currentColor`, like every other Opal icon. At 100 the pie fills,
 * then fades out as a green check fades in and the ring turns green.
 */
const SvgProgressCircle = ({
  value = 100,
  size,
  className,
  ...props
}: SvgProgressCircleProps) => {
  const progress = Math.min(Math.max(value, 0), 100);
  const complete = progress >= 100;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      stroke="currentColor"
      className={className}
      {...props}
    >
      {/* The ring: the outline of the whole. */}
      <circle
        cx="8"
        cy="8"
        r={RING_RADIUS}
        strokeWidth={1.5}
        className={cn(
          "transition-colors duration-150 ease-out motion-reduce:transition-none",
          // The green waits for the pie to fill. Leaving 100, it goes at once.
          complete && "text-status-success-05 delay-300"
        )}
      />
      {/* The pie: the share done, clockwise from the top. The offset is a
          style, not an attribute, so the CSS transition applies to it. */}
      <circle
        cx="8"
        cy="8"
        r={STROKE_RADIUS}
        strokeWidth={PIE_RADIUS}
        strokeDasharray={CIRCUMFERENCE}
        transform="rotate(-90 8 8)"
        style={{
          strokeDashoffset: CIRCUMFERENCE * (1 - progress / 100),
        }}
        className={cn(
          "motion-reduce:transition-none",
          complete
            ? "opacity-0 [transition:stroke-dashoffset_300ms_ease-out,opacity_150ms_ease-out_300ms]"
            : "[transition:stroke-dashoffset_300ms_ease-out]"
        )}
      />
      {/* The check: fades in once the pie is full. */}
      <path
        d="M5.333 8.333L7.167 10L10.667 6"
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeLinejoin="round"
        className={cn(
          "text-status-success-05 transition-opacity duration-150 ease-out motion-reduce:transition-none",
          complete ? "opacity-100 delay-300" : "opacity-0"
        )}
      />
    </svg>
  );
};

export default SvgProgressCircle;
