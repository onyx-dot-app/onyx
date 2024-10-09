"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { LLMConfiguration } from "./LLMConfiguration";
import { CpuIcon } from "@/components/icons/icons";

const Page = () => {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="LLM Setup"
        icon={<CpuIcon size={32} className="my-auto" />}
      />

      <LLMConfiguration />
    </div>
  );
};

export default Page;
