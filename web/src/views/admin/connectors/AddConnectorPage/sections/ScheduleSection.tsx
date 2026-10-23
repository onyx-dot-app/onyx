import { useTranslations } from "next-intl";
import { Card, Collapsible, InputDatePicker } from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
import { FormikField } from "@/refresh-components/form/FormikField";
import { InputNumberField } from "@opal/form";
import {
  MAX_PRUNE_FREQ_HOURS,
  MAX_REFRESH_FREQ_MINUTES,
  MIN_PRUNE_FREQ_HOURS,
  MIN_REFRESH_FREQ_MINUTES,
} from "@/lib/connectors/connectors";

interface ScheduleSectionProps {
  /** Shows Run Checks Every: the source has checks of its own. */
  showCheckFreq?: boolean;
  /** Freezes the section while the page locks the configuration. */
  disabled?: boolean;
}

// `indexingStart` is stored as a "YYYY-MM-DD" string. Read and write it in
// local time so the picked day does not shift across time zones.
function parseIndexingStart(value: string | null | undefined): Date | null {
  if (!value) return null;
  const [year, month, day] = value.split("-").map(Number);
  if (!year || !month || !day) return null;
  return new Date(year, month - 1, day);
}

function formatIndexingStart(date: Date | null): string {
  if (!date) return "";
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

interface IndexingStartFieldProps {
  disabled?: boolean;
}

/** The date before which the connector indexes nothing. The Index
 * Configurations section shows it. */
export function IndexingStartField({ disabled }: IndexingStartFieldProps) {
  const t = useTranslations("admin.connectorsList.scheduled");
  return (
    <InputHorizontal
      withLabel="indexingStart"
      disabled={disabled}
      title={t("indexingStart.title")}
      description={t("indexingStart.description")}
      suffix="optional"
      fillInput
      center
    >
      <FormikField<string | undefined>
        name="indexingStart"
        render={(field, helper) => (
          <InputDatePicker
            id="indexingStart"
            value={parseIndexingStart(field.value)}
            onChange={(date) => helper.setValue(formatIndexingStart(date))}
            placeholder={t("indexingStart.placeholder")}
            clearable
            disabled={disabled}
          />
        )}
      />
    </InputHorizontal>
  );
}

/** The connector's schedule: refresh and prune frequency. */
export default function ScheduleSection({
  showCheckFreq = false,
  disabled,
}: ScheduleSectionProps) {
  const t = useTranslations("admin.connectorsList.scheduled");

  return (
    <Collapsible
      title={t("title")}
      description={t("description")}
      disabled={disabled}
    >
      <Card border="solid" rounding={4} padding={4} disabled={disabled}>
        <Section alignItems="stretch" gap={4}>
          <InputHorizontal
            withLabel="refreshFreq"
            disabled={disabled}
            title={t("refreshFrequency.title")}
            description={t("refreshFrequency.description")}
            fillInput
            center
          >
            <InputNumberField
              name="refreshFreq"
              min={MIN_REFRESH_FREQ_MINUTES}
              max={MAX_REFRESH_FREQ_MINUTES}
              suffix={t("units.minutes")}
              disabled={disabled}
            />
          </InputHorizontal>

          <InputHorizontal
            withLabel="pruneFreq"
            disabled={disabled}
            title={t("pruneFrequency.title")}
            description={t("pruneFrequency.description")}
            fillInput
            center
          >
            <InputNumberField
              name="pruneFreq"
              min={MIN_PRUNE_FREQ_HOURS}
              max={MAX_PRUNE_FREQ_HOURS}
              decimalPlaces={3}
              suffix={t("units.hours")}
              disabled={disabled}
            />
          </InputHorizontal>

          {showCheckFreq && (
            <InputHorizontal
              withLabel="checkFreq"
              disabled={disabled}
              title={t("checkFrequency.title")}
              suffix="optional"
              description={t("checkFrequency.description")}
              fillInput
              center
            >
              <InputNumberField
                name="checkFreq"
                // The backend's minimum and maximum match pruning's.
                min={MIN_PRUNE_FREQ_HOURS}
                max={MAX_PRUNE_FREQ_HOURS}
                decimalPlaces={3}
                // Cleared, the checks run only on request.
                placeholder={t("checkFrequency.placeholder")}
                suffix={t("units.hours")}
                disabled={disabled}
              />
            </InputHorizontal>
          )}
        </Section>
      </Card>
    </Collapsible>
  );
}
