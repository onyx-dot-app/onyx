import { useMemo } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { Text } from "@opal/components";
import { Section } from "@opal/layouts";
import {
  computeDiff,
  countDiffLines,
} from "@/lib/timeline/components/bodies/diffLines";

interface DiffStatProps {
  added: number;
  removed: number;
}

/** The `+N -M` line counts of a change; a zero count is left out. */
export function DiffStat({ added, removed }: DiffStatProps) {
  const t = useTranslations("craft.toolCards.diff");
  const format = useFormatter();
  const compact = (value: number) =>
    format.number(value, { notation: "compact", maximumFractionDigits: 1 });
  if (added === 0 && removed === 0) return null;
  return (
    <Section
      flexDirection="row"
      width="fit"
      gap={0.25}
      role="group"
      aria-label={t("stat.label", { added, removed })}
    >
      {added > 0 && (
        <Text font="secondary-mono" color="status-success-05">
          {`+${compact(added)}`}
        </Text>
      )}
      {removed > 0 && (
        <Text font="secondary-mono" color="status-error-05">
          {`-${compact(removed)}`}
        </Text>
      )}
    </Section>
  );
}

interface TextDiffStatProps {
  oldText: string;
  newText: string;
}

/** The line counts of the change from `oldText` to `newText`. */
export function TextDiffStat({ oldText, newText }: TextDiffStatProps) {
  const counts = useMemo(
    () => countDiffLines(computeDiff(oldText, newText)),
    [oldText, newText]
  );
  return <DiffStat added={counts.added} removed={counts.removed} />;
}
