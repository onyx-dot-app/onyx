import { useTranslations } from "next-intl";
import {
  Card,
  Collapsible,
  InputDatePicker,
  InputNumber,
} from "@opal/components";
import { InputHorizontal, Section } from "@opal/layouts";
import { FormikField } from "@/refresh-components/form/FormikField";
import {
  defaultRefreshFreqMinutes,
  MAX_PRUNE_FREQ_HOURS,
  MAX_REFRESH_FREQ_MINUTES,
  MIN_PRUNE_FREQ_HOURS,
  MIN_REFRESH_FREQ_MINUTES,
} from "@/lib/connectors/connectors";

interface AdvancedFormPageProps {
  defaultPruneFreqHours?: number;
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

/** The connector's schedule: refresh and prune frequency, and the start date. */
export default function AdvancedFormPage({
  defaultPruneFreqHours = 600,
  disabled,
}: AdvancedFormPageProps) {
  const t = useTranslations("admin.connectorsList.scheduled");

  return (
    <Collapsible
      title={t("title")}
      description={t("description")}
      defaultOpen={false}
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
            <FormikField<number | undefined>
              name="refreshFreq"
              render={(field, helper) => (
                <InputNumber
                  id="refreshFreq"
                  value={field.value ?? null}
                  onChange={(value) => {
                    // InputNumber has no blur callback, so touch on change to
                    // show the field's validation error.
                    helper.setTouched(true, false);
                    helper.setValue(value ?? undefined);
                  }}
                  min={MIN_REFRESH_FREQ_MINUTES}
                  max={MAX_REFRESH_FREQ_MINUTES}
                  placeholder={String(defaultRefreshFreqMinutes)}
                  suffix={t("units.minutes")}
                  disabled={disabled}
                />
              )}
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
            <FormikField<number | undefined>
              name="pruneFreq"
              render={(field, helper) => (
                <InputNumber
                  id="pruneFreq"
                  value={field.value ?? null}
                  onChange={(value) => {
                    helper.setTouched(true, false);
                    helper.setValue(value ?? undefined);
                  }}
                  min={MIN_PRUNE_FREQ_HOURS}
                  max={MAX_PRUNE_FREQ_HOURS}
                  decimalPlaces={3}
                  placeholder={String(defaultPruneFreqHours)}
                  suffix={t("units.hours")}
                  disabled={disabled}
                />
              )}
            />
          </InputHorizontal>

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
                  onChange={(date) =>
                    helper.setValue(formatIndexingStart(date))
                  }
                  placeholder={t("indexingStart.placeholder")}
                  clearable
                  disabled={disabled}
                />
              )}
            />
          </InputHorizontal>
        </Section>
      </Card>
    </Collapsible>
  );
}
