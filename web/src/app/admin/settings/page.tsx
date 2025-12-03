import { AdminPageTitle } from "@/components/admin/Title";
import { SettingsForm } from "./SettingsForm";
import Text from "@/components/ui/text";
import SvgSettings from "@/icons/settings";

export default async function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Workspace Settings"
        icon={<SvgSettings className="stroke-text-04 h-8 w-8 my-auto" />}
      />

      <Text className="mb-8">
        Manage general Onyx settings applicable to all users in the workspace.
      </Text>

      <SettingsForm />
    </div>
  );
}
