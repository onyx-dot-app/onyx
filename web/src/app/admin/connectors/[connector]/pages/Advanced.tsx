import i18n from "i18next";
import k from "./../../../../../i18n/keys";
import React from "react";
import NumberInput from "./ConnectorInput/NumberInput";
import { TextFormField } from "@/components/admin/connectors/Field";
import { TrashIcon } from "@/components/icons/icons";

const AdvancedFormPage = () => {
  return (
    <div className="py-4 flex flex-col gap-y-6 rounded-lg max-w-2xl mx-auto">
      <h2 className="text-2xl font-bold mb-4 text-text-800">
        {i18n.t(k.ADVANCED_CONFIGURATION)}
      </h2>

      <NumberInput
        description={`
          ${i18n.t(k.CHECKS_ALL_DOCUMENTS_AGAINST_T)}
        `}
        label="Prune Frequency (days)"
        name="pruneFreq"
      />

      <NumberInput
        description="This is how frequently we pull new documents from the source (in minutes). If you input 0, we will never pull new documents for this connector."
        label="Refresh Frequency (minutes)"
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext="Documents prior to this date will not be pulled in"
        optional
        label="Indexing Start Date"
        name="indexingStart"
      />

      <div className="mt-4 flex w-full mx-auto max-w-2xl justify-start">
        <button className="flex gap-x-1 bg-red-500 hover:bg-red-500/80 items-center text-white py-2.5 px-3.5 text-sm font-regular rounded ">
          <TrashIcon size={20} className="text-white" />
          <div className="w-full items-center gap-x-2 flex">
            {i18n.t(k.RESET)}
          </div>
        </button>
      </div>
    </div>
  );
};

export default AdvancedFormPage;
