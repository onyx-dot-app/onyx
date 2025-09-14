"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "./../../../../i18n/keys";
import { AdminPageTitle } from "@/components/admin/Title";
import { LLMConfiguration } from "./LLMConfiguration";
import { CpuIcon } from "@/components/icons/icons";

const Page = () => {
  const { t } = useTranslation();
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title={t(k.LLM_SETTINGS)}
        icon={<CpuIcon size={32} className="my-auto" />}
      />

      <LLMConfiguration />
    </div>
  );
};

export default Page;
