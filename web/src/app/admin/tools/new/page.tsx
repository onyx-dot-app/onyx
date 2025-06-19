"use client";

import { ToolEditor } from "@/app/admin/tools/ToolEditor";
import { BackButton } from "@/components/BackButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CardSection from "@/components/admin/CardSection";

export default function NewToolPage() {
  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle
        title="Create Tool"
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      <CardSection>
        <ToolEditor />
      </CardSection>
    </div>
  );
}
