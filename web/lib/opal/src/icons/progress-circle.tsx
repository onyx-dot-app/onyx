import { cn } from "@/lib/utils";
import SvgCheckCircle from "@opal/icons/check-circle";
import type { IconProps } from "@opal/types";

export interface SvgProgressCircleProps extends IconProps {
  value?: number;
}

const SvgProgressCircle = ({
  value = 100,
  className,
  ...props
}: SvgProgressCircleProps) => {
  // Clamp value between 0 and 100
  const progress = Math.min(Math.max(value, 0), 100);
  const isComplete = progress >= 100;

  // Calculate circumference for circular progress
  // For a stroke to fill from center to radius R, we need:
  // - Circle at radius R/2 with strokeWidth R
  // This way stroke extends from 0 to R (R/2 - R/2 to R/2 + R/2)
  const maxRadius = 5; // Maximum inner circle radius
  const strokeRadius = maxRadius / 2; // Position circle at half the desired radius
  const strokeWidth = maxRadius; // Stroke width equals max radius
  const circumference = 2 * Math.PI * strokeRadius;
  // Calculate how much of the circle to show (inverted for clockwise from top)
  const offset = circumference - (progress / 100) * circumference;

  return (
    <div className={className}>
      {isComplete ? (
        <SvgCheckCircle
          className={cn(className, "!stroke-status-success-05")}
          {...props}
        />
      ) : (
        <svg
          width="16"
          height="16"
          viewBox="0 0 16 16"
          fill="none"
          xmlns="http://www.w3.org/2000/svg"
        >
          {/* Outer circle - outline only */}
          <circle
            cx="8"
            cy="8"
            r="7"
            stroke="currentColor"
            strokeWidth="1.5"
            fill="none"
            className="text-border-medium"
          />

          {/* Inner circle progress - fills like a pie using thick stroke */}
          <circle
            cx="8"
            cy="8"
            r={strokeRadius}
            stroke="currentColor"
            strokeWidth={strokeWidth}
            fill="none"
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            className="-rotate-90 origin-center"
            style={{
              transformOrigin: "center",
            }}
          />
        </svg>
      )}
    </div>
  );
};

export default SvgProgressCircle;
