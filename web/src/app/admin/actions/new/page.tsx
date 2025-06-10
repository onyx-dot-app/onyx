"use client";

import { ActionEditor } from "@/app/admin/actions/ActionEditor";
import { BackButton } from "@/components/BackButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CardSection from "@/components/admin/CardSection";

export default function NewToolPage() {
  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle
        title="Create Action"
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      <CardSection>
        <ActionEditor />
      </CardSection>
    </div>
  );
}
