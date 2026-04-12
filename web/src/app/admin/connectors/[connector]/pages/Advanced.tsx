import React from "react";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/Field";
import { Button } from "@opal/components";
import { SvgTrash } from "@opal/icons";
import { useTranslations } from "next-intl";

export default function AdvancedFormPage() {
  const t = useTranslations("admin.connectors");

  return (
    <div className="py-4 flex flex-col gap-y-6 rounded-lg max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-text-800">
        {t("advancedConfiguration")}
      </h2>

      <NumberInput
        description={t("pruneFrequencyDescription")}
        label={t("pruneFrequencyLabel")}
        name="pruneFreq"
      />

      <NumberInput
        description={t("refreshFrequencyDescription")}
        label={t("refreshFrequencyLabel")}
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext={t("indexingStartDateDescription")}
        optional
        label={t("indexingStartDate")}
        name="indexingStart"
      />
      <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
        <Button variant="danger" icon={SvgTrash} type="submit">
          {t("reset")}
        </Button>
      </div>
    </div>
  );
}
