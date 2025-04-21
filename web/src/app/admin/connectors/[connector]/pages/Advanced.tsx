import i18n from "@/i18n/init";
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
        label="Частота удаления (дней)"
        name="pruneFreq"
      />

      <NumberInput
        description="Это частота, с которой мы извлекаем новые документы из источника (в минутах). Если ввести 0, мы никогда не будем извлекать новые документы для этого коннектора."
        label="Частота обновления (минут)"
        name="refreshFreq"
      />

      <TextFormField
        type="date"
        subtext="Документы до этой даты не будут извлечены"
        optional
        label="Дата начала индексации"
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
