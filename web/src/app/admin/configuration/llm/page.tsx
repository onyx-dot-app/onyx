"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { LLMConfiguration } from "./LLMConfiguration";
import SvgCpu from "@/icons/cpu";

export default function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle title="LLM Setup" icon={SvgCpu} />

      <LLMConfiguration />
    </div>
  );
}
