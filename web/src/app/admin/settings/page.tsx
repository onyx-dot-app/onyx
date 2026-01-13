"use client";

import { AdminPageTitle } from "@/components/admin/Title";
import { SettingsForm } from "@/app/admin/settings/SettingsForm";
import Text from "@/components/ui/text";
import { SvgSettings } from "@opal/icons";
export default function Page() {
  return (
    <>
      <AdminPageTitle title="Workspace Settings" icon={SvgSettings} />

      <Text className="mb-8">
        Manage general Onyx settings applicable to all users in the workspace.
      </Text>

      <SettingsForm />
    </>
  );
}
