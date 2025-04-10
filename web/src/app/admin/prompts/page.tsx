import { AdminPageTitle } from "@/components/admin/Title";
import Text from "@/components/ui/text";
import { DatabaseIcon } from "@/components/icons/icons";
import Prompts from './Prompts';

export default async function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Prompts"
        icon={<DatabaseIcon size={32} className="my-auto" />}
      />

      <Text className="mb-8">
        View and edit system prompts used across the application.
      </Text>

      <Prompts />
    </div>
  );
} 