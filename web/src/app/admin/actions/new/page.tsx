"use client";

import { ActionEditor } from "@/app/admin/actions/ActionEditor";
import { BackButton } from "@/components/BackButton";
import { AdminPageTitle } from "@/components/admin/Title";
import CardSection from "@/components/admin/CardSection";
import { SvgActions } from "@opal/icons";
export default function NewToolPage() {
  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle title="Create Action" icon={SvgActions} />

      <CardSection>
        <ActionEditor />
      </CardSection>
    </div>
  );
}
