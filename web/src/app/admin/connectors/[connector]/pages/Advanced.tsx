"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../../i18n/keys";
import React from "react";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/admin/connectors/Field";
import { TrashIcon } from "@/components/icons/icons";

const AdvancedFormPage = () => {
  const { t } = useTranslation();
  return (
    <div className="py-4 flex flex-col gap-y-6 rounded-lg max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-text-800">
        {t(k.ADVANCED_CONFIGURATION)}
      </h2>

      <NumberInput
        description={`
${t(k.CHECKS_ALL_DOCUMENTS_AGAINST_T)}
`}
        label={t(k.DELETION_FREQUENCY_LABEL)}
        name="pruneFreq"
      />

      <NumberInput
        description={t(k.UPDATE_FREQUENCY_DESCRIPTION)}
        label={t(k.UPDATE_FREQUENCY_LABEL)}
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext={t(k.INDEXING_START_DATE_SUBTEXT)}
        optional
        label={t(k.INDEXING_START_DATE_LABEL)}
        name="indexingStart"
      />

      <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
        <button className="flex gap-x-1 bg-red-500 hover:bg-red-500/80 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded ">
          <TrashIcon size={20} className="text-white" />
          <div className="w-full items-center gap-x-2 flex">{t(k.RESET)}</div>
        </button>
      </div>
    </div>
  );
};

export default AdvancedFormPage;
