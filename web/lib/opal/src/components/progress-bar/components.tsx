import "@opal/components/progress-bar/styles.css";
import { cn } from "@opal/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type ProgressBarColor = "blue" | "green" | "red" | "purple";

const FILL_COLORS: Record<ProgressBarColor, string> = {
  blue: "bg-theme-blue-05",
  green: "bg-theme-green-05",
  red: "bg-status-error-05",
  purple: "bg-theme-purple-05",
};

interface ProgressBarProps {
  value: number;
  /** @default 100 */
  max?: number;
  /** @default "blue" */
  color?: ProgressBarColor;
  ref?: React.Ref<HTMLDivElement>;
}

// ---------------------------------------------------------------------------
// ProgressBar
// ---------------------------------------------------------------------------

/** Determinate progress bar; fill fraction = value / max, clamped to [0, 1]. */
function ProgressBar({
  value,
  max = 100,
  color = "blue",
  ref,
}: ProgressBarProps) {
  const fraction = max > 0 ? Math.min(1, Math.max(0, value / max)) : 0;

  return (
    <div
      ref={ref}
      className="opal-progress-bar bg-background-tint-00"
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={max}
    >
      <div
        className={cn("opal-progress-bar-fill", FILL_COLORS[color])}
        style={{ width: `${fraction * 100}%` }}
      />
    </div>
  );
}

export { ProgressBar, type ProgressBarProps, type ProgressBarColor };
