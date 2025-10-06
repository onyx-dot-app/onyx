"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { LLMConfiguration } from "./LLMConfiguration";
import { CpuIcon } from "@/components/icons/icons";

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="LLM Setup"
        icon={<CpuIcon size={32} className="my-auto" />}
      />

      <LLMConfiguration />
    </div>
  );
}
