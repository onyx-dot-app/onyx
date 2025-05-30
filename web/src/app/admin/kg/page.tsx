import { AdminPageTitle } from "@/components/admin/Title";
import { BrainIcon } from "@/components/icons/icons";

export default async function Page() {
  return (
    <div className="mx-auto container">
      <AdminPageTitle
        title="Knowledge Graph"
        icon={<BrainIcon size={32} className="my-auto" />}
      />
    </div>
  );
}
