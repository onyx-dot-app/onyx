import { cn } from "@opal/utils";
import SvgCheckCircle from "@opal/icons/check-circle";
import type { IconProps } from "@opal/types";

export interface SvgProgressCircleProps extends IconProps {
  /** Progress from 0 to 100. 0 is an empty ring, 100 is a green check. */
  value?: number;
}

// The pie is a thick stroke on a circle at half the pie's radius, so the
// stroke spans from the centre out to the radius.
const PIE_RADIUS = 5;
const STROKE_RADIUS = PIE_RADIUS / 2;
const CIRCUMFERENCE = 2 * Math.PI * STROKE_RADIUS;

/**
 * A ring that fills like a pie as `value` rises, and turns into a green check
 * at 100. The pie animates between values.
 */
const SvgProgressCircle = ({
  value = 100,
  size,
  className,
  ...props
}: SvgProgressCircleProps) => {
  const progress = Math.min(Math.max(value, 0), 100);

  if (progress >= 100) {
    return (
      <SvgCheckCircle
        size={size}
        className={cn(className, "stroke-status-success-05!")}
        {...props}
      />
    );
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      {...props}
    >
      {/* The ring: the outline of the whole. */}
      <circle
        cx="8"
        cy="8"
        r="7"
        strokeWidth="1.5"
        fill="none"
        className="stroke-border-02"
      />
      {/* The pie: the share done, clockwise from the top. */}
      <circle
        cx="8"
        cy="8"
        r={STROKE_RADIUS}
        stroke="currentColor"
        strokeWidth={PIE_RADIUS}
        fill="none"
        strokeDasharray={CIRCUMFERENCE}
        strokeDashoffset={CIRCUMFERENCE - (progress / 100) * CIRCUMFERENCE}
        className="origin-center -rotate-90 transition-[stroke-dashoffset] duration-300 ease-out motion-reduce:transition-none"
      />
    </svg>
  );
};

export default SvgProgressCircle;
