import { ProgressRing } from "@opal/components";
import { SvgAlertCircle } from "@opal/icons";
import { Section } from "@opal/layouts";

export const FULL_PERCENT = 100;

interface UsageIconProps {
  /** Usage as a percent of the budget; may exceed 100. */
  percent: number;
}

/** The ring beside a usage percent, or a red alert once the budget is used
 *  up. Decorative: the percent text beside it carries the value. */
export default function UsageIcon({ percent }: UsageIconProps) {
  const atLimit = percent >= FULL_PERCENT;
  return (
    <Section
      gap={0}
      width={1.25}
      height={1.25}
      // The ring fills its 18px with a 1px inset, as in the mock.
      padding={atLimit ? 0.5 : 0.25}
      className={atLimit ? "text-status-error-05" : undefined}
    >
      {atLimit ? (
        <SvgAlertCircle size={16} aria-hidden />
      ) : (
        <ProgressRing value={percent} aria-hidden />
      )}
    </Section>
  );
}
