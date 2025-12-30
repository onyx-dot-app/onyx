"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { LLMConfiguration } from "./LLMConfiguration";
import { SvgCpu } from "@opal/icons";
export default function Page() {
  return (
    <div className="container">
      <AdminPageTitle title="LLM Setup" icon={SvgCpu} />

      <LLMConfiguration />
    </div>
  );
}
