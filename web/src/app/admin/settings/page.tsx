"use client";

import k from "./../../../i18n/keys";
import { useTranslation } from "@/hooks/useTranslation";
import { AdminPageTitle } from "@/components/admin/Title";

import { SettingsForm } from "./SettingsForm";
import Text from "@/components/ui/text";
import { SettingsIcon } from "@/components/icons/icons";

export default function Page() {
  const { t } = useTranslation();
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title={t(k.WORKSPACE_SETTINGS)}
        icon={<SettingsIcon size={32} className="my-auto" />}
      />

      <Text className="mb-8">{t(k.MANAGE_GENERAL_ONYX_SETTINGS_A)}</Text>

      <SettingsForm />
    </div>
  );
}
