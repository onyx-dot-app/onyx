"use client";

import { useTranslation } from "@/hooks/useTranslation";
import k from "../../../../i18n/keys";
import { ActionEditor } from "@/app/admin/actions/ActionEditor";
import { BackButton } from "@/components/BackButton";
import { AdminPageTitle } from "@/components/admin/Title";
import { ToolIcon } from "@/components/icons/icons";
import CardSection from "@/components/admin/CardSection";

export default function NewToolPage() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto container">
      <BackButton />

      <AdminPageTitle
        title={t(k.CREATE_TOOL)}
        icon={<ToolIcon size={32} className="my-auto" />}
      />

      <CardSection>
        <ActionEditor />
      </CardSection>
    </div>
  );
}
