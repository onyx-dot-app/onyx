import React from "react";
import { useTranslations } from "next-intl";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/Field";
import { Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
interface AdvancedFormPageProps {
  defaultPruneFreqHours?: number;
}

export default function AdvancedFormPage({
  defaultPruneFreqHours = 600,
}: AdvancedFormPageProps) {
  const t = useTranslations("admin.connectorsList");

  return (
    <div className="py-4 flex flex-col gap-y-6 rounded-lg max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-text-800">
        {t("advanced.title")}
      </h2>

      <NumberInput
        description={t("advanced.pruneFrequency.description", {
          hours: defaultPruneFreqHours,
          days: Math.round(defaultPruneFreqHours / 24),
        })}
        label={t("advanced.pruneFrequency.label")}
        name="pruneFreq"
      />

      <NumberInput
        description={t("advanced.refreshFrequency.description")}
        label={t("advanced.refreshFrequency.label")}
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext={t("advanced.indexingStart.subtext")}
        optional
        label={t("advanced.indexingStart.label")}
        name="indexingStart"
      />
      <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
        <Button variant="danger" icon={SvgTrash} type="submit">
          {t("advanced.resetButton.label")}
        </Button>
      </div>
    </div>
  );
}
