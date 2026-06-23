import React from "react";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/Field";
import { Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { useTranslation } from "react-i18next";
interface AdvancedFormPageProps {
  defaultPruneFreqHours?: number;
}

export default function AdvancedFormPage({
  defaultPruneFreqHours = 600,
}: AdvancedFormPageProps) {
  const { t } = useTranslation();
  return (
    <div className="py-4 flex flex-col gap-y-6 rounded-lg max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-text-800">
        {t("admin.connector_advanced.title")}
      </h2>

      <NumberInput
        description={t("admin.connector_advanced.prune_freq_desc", { hours: defaultPruneFreqHours, days: Math.round(defaultPruneFreqHours / 24) })}
        label={t("admin.connector_advanced.prune_freq_label")}
        name="pruneFreq"
      />

      <NumberInput
        description={t("admin.connector_advanced.refresh_freq_desc")}
        label={t("admin.connector_advanced.refresh_freq_label")}
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext={t("admin.connector_advanced.start_date_desc")}
        optional
        label={t("admin.connector_advanced.start_date_label")}
        name="indexingStart"
      />
      <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
        <Button variant="danger" icon={SvgTrash} type="submit">
          {t("admin.connector_advanced.reset_btn")}
        </Button>
      </div>
    </div>
  );
}
