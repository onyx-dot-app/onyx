import { cn } from "@opal/utils";
import type { IconProps } from "@opal/types";

export interface SvgProgressCircleProps extends IconProps {
  /** Progress from 0 to 100. 0 is an empty ring, 100 is a full green pie. */
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
 * values. Ring and pie use `currentColor`, like every other Opal icon, and
 * turn green once the pie is full at 100.
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
      className={cn(
        className,
        "transition-colors duration-150 ease-out motion-reduce:transition-none",
        // The green waits for the pie to fill. Leaving 100, it goes at once.
        complete && "text-status-success-05 delay-300"
      )}
      {...props}
    >
      {/* The ring: the outline of the whole. */}
      <circle cx="8" cy="8" r={RING_RADIUS} strokeWidth={1.5} />
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
        className="transition-[stroke-dashoffset] duration-300 ease-out motion-reduce:transition-none"
      />
    </svg>
  );
};

export default SvgProgressCircle;
